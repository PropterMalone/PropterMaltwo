#!/usr/bin/env python3
# pattern: imperative shell (test harness)
"""Regression tests for pass-support-accuracy.py — ADR-16's re-derived falsifier.

Pins the falsifier's input, denominator, and decision contracts:

  1. Denominator honesty. A non-REFUTED verdict with no `severity_opinion` had no
     severity judgment rendered (verifier-failure stubs, and every verdict predating
     ADR-14). Counting it as `agree` would inflate the denominator with silence and
     drive both strata toward zero — the exact starvation being fixed.
  2. REFUTED needs no `severity_opinion` to count as over-filed. It carries none by
     contract (verifier.md); refutation IS the severity judgment.
  3. The date floor holds. Pre-2026-08-09 runs are out of scope entirely, and so are
     runs whose date cannot be determined at all — the sentinel sorts ABOVE real dates,
     so a bare comparison admits them.
  4. k is the MAX across personas, so a finding one persona caught twice is
     corroborated even if another caught it once.
  5. The Critical-stratum guard blocks firing when the less-confounded stratum
     contradicts the pooled result — AND when that stratum is empty, which is
     unevaluable rather than passing.
  6. Corrupt input is excluded loudly, never silently: off-enum severities,
     unrecognized `severity_opinion` values, non-integer `pass_support`, and
     unreadable snapshots all surface in the output instead of quietly moving a rate.
  7. A zero corroborated over-filed rate — the strongest possible signal for the
     hypothesis — must be able to FIRE, not divide by zero into "unevaluable".

Run: scripts/test_pass_support_accuracy.py   (exit 0 = all pass)
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

DIR = Path(__file__).resolve().parent
SCRIPT = DIR / "pass-support-accuracy.py"
PASS, FAIL = 0, 0

# The module name has a hyphen, so it cannot be imported by name; load it by path to
# unit-test the pure helpers.
_spec = importlib.util.spec_from_file_location("psa", SCRIPT)
psa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(psa)


def check(name, got, want):
    global PASS, FAIL
    if got == want:
        print(f"ok   - {name}")
        PASS += 1
    else:
        print(f"FAIL - {name}\n         got:  {got!r}\n         want: {want!r}")
        FAIL += 1


def finding(fid, k, N=2, sev="important", verdict="CONFIRMED", opinion="agree",
            second_persona_k=None, pass_support=None):
    """A snapshot finding with the pass_support / verification shape the scanner reads."""
    ps = {"hyper": [k, N]}
    if second_persona_k is not None:
        ps["rigor"] = [second_persona_k, N]
    if pass_support is not None:
        ps = pass_support
    f = {"id": fid, "severity": sev, "pass_support": ps}
    if verdict is not None:
        v = {"id": fid, "verdict": verdict, "method": "ran", "evidence": "e"}
        if opinion is not None:
            v["severity_opinion"] = opinion
        f["verification"] = v
    return f


def make_run(root, run_id, findings, date=None):
    d = root / run_id
    d.mkdir(parents=True, exist_ok=True)
    body = {"version": 2, "project": "fixture", "findings": findings}
    if date is not None:
        body["date"] = date
    (d / "findings-snapshot.json").write_text(json.dumps(body), encoding="utf-8")
    return d


def raw_tool(root, *extra):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--runs-dir", str(root), "--json", *extra],
        capture_output=True, text=True)


def run_tool(root, *extra):
    out = raw_tool(root, *extra)
    if out.returncode != 0:
        print(out.stderr, file=sys.stderr)
        raise SystemExit(f"tool exited {out.returncode}")
    return json.loads(out.stdout)


# --- 1. what counts as over-filed, and what counts at all ---------------------
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    make_run(root, "20260810T000000Z-aaaaaaaa", [
        finding("f1", k=1, verdict="REFUTED", opinion=None),        # over-filed, no opinion
        finding("f2", k=1, opinion="too-high"),                     # over-filed
        finding("f3", k=1, opinion="agree"),                        # counted, not over-filed
        finding("f4", k=1, opinion="too-low"),                      # counted, not over-filed
        finding("f5", k=1, opinion=None),                           # EXCLUDED: no judgment
        finding("f6", k=1, verdict=None),                           # EXCLUDED: unverified
        finding("f7", k=1, N=1),                                    # EXCLUDED: not multiball
    ])
    r = run_tool(root)
    check("REFUTED + too-high count as over-filed", r["singleton"]["over_filed"], 2)
    check("agree/too-low counted in denominator only", r["singleton"]["n"], 4)
    # 7 findings, 3 excluded: the no-opinion stub, the unverified one, the single-pass one.
    # If the stub were read as `agree` the denominator would be 5, not 4.
    check("k>=2 stratum empty here", r["corroborated"]["n"], 0)
    check("no spurious data issues on clean input", r["data_issues"], [])

# --- 2. date floor, and undatable runs --------------------------------------
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    make_run(root, "20260801T000000Z-bbbbbbbb", [finding("f1", k=1, opinion="too-high")])
    make_run(root, "20260810T000000Z-cccccccc", [finding("f1", k=1, opinion="too-high")])
    r = run_tool(root)
    check("pre-ADR-14 run excluded by the default floor", r["singleton"]["n"], 1)
    check("runs_in_scope counts only post-floor runs", r["runs_in_scope"], 1)
    r2 = run_tool(root, "--since", "2026-07-01")
    check("--since override widens the window", r2["singleton"]["n"], 2)

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    # No `date` field and a non-YYYYMMDD directory stem -> undatable. The sentinel
    # '????-??-??' sorts ABOVE every real date, so `date < since` would ADMIT this run.
    make_run(root, "undatable-run-xyz", [finding("f1", k=1, opinion="too-high")])
    make_run(root, "20260810T000000Z-dddddddd", [finding("f1", k=1, opinion="agree")])
    r = run_tool(root)
    check("undatable run is excluded, not admitted", r["singleton"]["n"], 1)
    check("undatable exclusion is reported", r["runs_undatable_excluded"], 1)
    check("undatable run does not leak an over-filed count", r["singleton"]["over_filed"], 0)

# --- 3. k is the max across personas -----------------------------------------
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    make_run(root, "20260810T000000Z-dddddddd", [
        finding("f1", k=1, second_persona_k=2, opinion="agree"),
    ])
    r = run_tool(root)
    check("k=max across personas -> corroborated", (r["singleton"]["n"], r["corroborated"]["n"]), (0, 1))

# --- 4. all clauses must hold; a fired corpus fires --------------------------
def corpus(n1, over1, n2, over2, crits=()):
    fs = []
    for i in range(n1):
        fs.append(finding(f"s{i}", k=1, opinion="too-high" if i < over1 else "agree"))
    for i in range(n2):
        fs.append(finding(f"c{i}", k=2, opinion="too-high" if i < over2 else "agree"))
    fs.extend(crits)
    return fs


def criticals(k1_n, k1_over, k2_n, k2_over):
    """A Critical stratum with an explicit denominator in BOTH k buckets."""
    out = []
    for i in range(k1_n):
        out.append(finding(f"kc{i}", k=1, sev="critical",
                           opinion="too-high" if i < k1_over else "agree"))
    for i in range(k2_n):
        out.append(finding(f"kd{i}", k=2, sev="critical",
                           opinion="too-high" if i < k2_over else "agree"))
    return out


with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    # Importants 30% vs 10%; Criticals 30% vs 10% so the guard agrees. Pooled: k=1
    # 33/110 = 30%, k>=2 9/90 = 10% -> 3.0x, both n floors cleared.
    make_run(root, "20260810T000000Z-eeeeeeee",
             corpus(100, 30, 80, 8, crits=criticals(10, 3, 10, 1)))
    r = run_tool(root)
    check("fired corpus: all clauses true", r["clauses"],
          {"powered": True, "absolute": True, "ratio": True,
           "uncontradicted": True, "critical_stratum_evaluable": True})
    check("fired corpus: verdict FIRED", r["verdict"], "FIRED")
    check("fired corpus: ratio 3.0x", round(r["ratio"], 2), 3.0)

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    # Identical pooled shape, but ZERO Criticals. The guard has no denominator, so it is
    # unevaluable and must not wave the corpus through.
    make_run(root, "20260810T000000Z-eeee0000", corpus(100, 30, 80, 8))
    r = run_tool(root)
    check("no-Critical corpus: stratum flagged unevaluable",
          r["clauses"]["critical_stratum_evaluable"], False)
    check("no-Critical corpus: guard does not pass vacuously",
          r["clauses"]["uncontradicted"], False)
    check("no-Critical corpus: blocked from firing", r["verdict"], "not met")
    check("no-Critical corpus: the other three clauses still hold",
          [r["clauses"][k] for k in ("powered", "absolute", "ratio")], [True, True, True])

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    make_run(root, "20260810T000000Z-ffffffff",
             corpus(50, 15, 40, 4, crits=criticals(10, 3, 10, 1)))
    r = run_tool(root)
    check("under-powered corpus does not fire", r["verdict"], "not met")
    check("under-powered: only the powered clause fails", r["clauses"]["powered"], False)
    check("under-powered: ratio clause still true", r["clauses"]["ratio"], True)

# --- 5. the Critical-stratum confound guard ----------------------------------
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    # Pooled stays above 2.0x, but Criticals point the other way (k=1 0/10 vs k>=2 5/10).
    # The pooled effect is an admission artifact, so firing must be blocked.
    make_run(root, "20260810T000000Z-99999999",
             corpus(120, 48, 80, 8, crits=criticals(10, 0, 10, 5)))
    r = run_tool(root)
    check("confounded corpus: pooled ratio clause still passes", r["clauses"]["ratio"], True)
    check("confounded corpus: Critical stratum is evaluable",
          r["clauses"]["critical_stratum_evaluable"], True)
    check("confounded corpus: Critical stratum contradicts", r["clauses"]["uncontradicted"], False)
    check("confounded corpus: blocked from firing", r["verdict"], "not met")

# --- 6. a zero corroborated rate is the strongest signal, and must fire ------
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    # k>=2 over-filed rate is exactly 0. A guarded division would call this unevaluable
    # and refuse to fire on the best evidence the hypothesis could ever produce.
    make_run(root, "20260810T000000Z-77777777",
             corpus(100, 30, 80, 0, crits=criticals(10, 3, 10, 0)))
    r = run_tool(root)
    check("zero corroborated rate -> ratio is infinite, not null", r["ratio"], float("inf"))
    check("zero corroborated rate satisfies the ratio clause", r["clauses"]["ratio"], True)
    check("zero corroborated rate can FIRE", r["verdict"], "FIRED")

# --- 7. corrupt input is excluded loudly, never silently ---------------------
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    make_run(root, "20260810T000000Z-66666666", [
        finding("ok1", k=1, opinion="too-high"),
        finding("bad-sev", k=1, sev="refuted", opinion="too-high"),      # off-enum severity
        finding("bad-op", k=1, opinion="Too-High"),                      # cased -> normalizes
        finding("bad-op2", k=1, opinion="definitely-too-high"),          # invalid enum value
        finding("bad-ps", k=1, pass_support={"hyper": ["a", "b"]}),      # non-integer scalars
    ])
    r = run_tool(root)
    check("off-enum severity excluded from the denominator", r["singleton"]["n"], 2)
    # A case-sensitive `opinion == "too-high"` test let 'Too-High' into the denominator
    # and scored it as agreement — inverting the very judgment it records. Both rows
    # here are over-filed, so over_filed must equal n.
    check("cased severity_opinion normalizes instead of reading as agreement",
          (r["singleton"]["over_filed"], r["singleton"]["n"]), (2, 2))
    check("every corrupt row is reported, none silently dropped", len(r["data_issues"]), 3)
    reasons = " ".join(i["reason"] for i in r["data_issues"])
    check("off-enum severity names the offending value", "'refuted'" in reasons, True)
    check("an unrecognized severity_opinion is excluded, not read as agreement",
          "unrecognized severity_opinion" in reasons, True)
    check("non-integer pass_support is caught, not crashed on",
          "non-integer pass_support" in reasons, True)

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    # A whole run whose snapshot will not parse. Silently skipping it produces a
    # legitimate-looking result on a denominator nobody audited.
    d = root / "20260810T000000Z-55555555"
    d.mkdir(parents=True)
    (d / "findings-snapshot.json").write_text("{not json", encoding="utf-8")
    make_run(root, "20260810T000000Z-44444444", [finding("f1", k=1, opinion="agree")])
    r = run_tool(root)
    check("unreadable snapshot is reported", len(r["snapshots_unreadable"]), 1)
    check("unreadable snapshot names a parse reason",
          "JSONDecodeError" in r["snapshots_unreadable"][0]["reason"], True)
    check("readable runs still counted alongside it", r["runs_in_scope"], 1)

# --- 8. --since is validated -------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    make_run(root, "20260810T000000Z-33333333", [finding("f1", k=1, opinion="agree")])
    out = raw_tool(root, "--since", "garbage")
    # Unvalidated, 'garbage' sorts above every real date: every run is skipped and the
    # tool reports a clean empty corpus at exit 0.
    check("malformed --since exits non-zero", out.returncode, 2)
    check("malformed --since explains itself", "YYYY-MM-DD" in out.stderr, True)
    check("well-formed --since still works", run_tool(root, "--since", "2026-08-09")["runs_in_scope"], 1)

# --- 9. stratification: severity, multiball N, and per-run ------------------
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    make_run(root, "20260810T000000Z-22222222", [
        finding("i1", k=1, N=2, opinion="too-high"),
        finding("c1", k=1, N=2, sev="critical", opinion="agree"),
        finding("m1", k=1, N=2, sev="minor", opinion="agree"),
        finding("n1", k=1, N=3, sev="noted", opinion="agree"),
        finding("i2", k=2, N=3, opinion="agree"),
    ])
    r = run_tool(root)
    # minor/noted count toward the pooled denominator but have no severity stratum of
    # their own — before 2026-08-25 no fixture carried a third severity at all.
    check("pooled counts every severity", r["singleton"]["n"] + r["corroborated"]["n"], 5)
    check("severity strata cover critical and important only",
          sorted(r["by_severity"]), ["critical", "important"])
    check("minor/noted are pooled but unstratified",
          r["by_severity"]["important"]["k1"][1] + r["by_severity"]["critical"]["k1"][1], 2)
    check("multiball N stratification is emitted", sorted(r["by_multiball_n"]), ["2", "3"])
    check("N=2 stratum holds the three N=2 findings", r["by_multiball_n"]["2"]["k1"][1], 3)
    check("N=3 stratum splits k correctly",
          (r["by_multiball_n"]["3"]["k1"][1], r["by_multiball_n"]["3"]["k2"][1]), (1, 1))
    check("per-run k=1 breakdown is emitted, not dead",
          r["per_run_k1"]["20260810T000000Z-22222222"], {"over_filed": 1, "n": 4})

# --- 10. the per-run noise baseline -----------------------------------------
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    # Two runs of 4 judged singletons each, one of them at 25%. At a base rate this low,
    # a 25% reading on n=4 is what noise produces — the baseline says so out loud.
    make_run(root, "20260810T000000Z-11111111",
             [finding(f"a{i}", k=1, opinion="too-high" if i == 0 else "agree") for i in range(4)])
    make_run(root, "20260811T000000Z-12121212",
             [finding(f"b{i}", k=1, opinion="agree") for i in range(4)])
    r = run_tool(root)
    nb = r["per_run_noise_baseline"]
    check("noise baseline counts quotable runs only", nb["runs_quotable"], 2)
    check("noise baseline counts observed crossings", nb["observed_at_or_above"], 1)
    check("noise baseline reports an expectation", nb["expected_by_chance"] > 0, True)
    check("noise baseline reports P(>= observed)", 0.0 <= nb["p_at_least_observed"] <= 1.0, True)
    check("noise baseline reports the max per-run rate", round(nb["max_rate_pct"], 1), 25.0)

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    # 3 judged singletons is below MIN_RUN_SINGLETONS: at n=3 the reachable rates are
    # 0/33/67/100%, so a "crossing" carries no information at all.
    make_run(root, "20260810T000000Z-13131313",
             [finding(f"a{i}", k=1, opinion="too-high" if i == 0 else "agree") for i in range(3)])
    r = run_tool(root)
    check("runs below the quotable floor produce no baseline", r["per_run_noise_baseline"], None)

# --- 11. two_prop_p, which had no coverage at all ---------------------------
check("two_prop_p: identical proportions -> p = 1.0", round(psa.two_prop_p(10, 100, 10, 100), 6), 1.0)
check("two_prop_p: empty first group -> None", psa.two_prop_p(0, 0, 10, 100), None)
check("two_prop_p: empty second group -> None", psa.two_prop_p(10, 100, 0, 0), None)
check("two_prop_p: zero variance (both all-success) -> None", psa.two_prop_p(50, 50, 50, 50), None)
check("two_prop_p: zero variance (both all-failure) -> None", psa.two_prop_p(0, 50, 0, 50), None)
check("two_prop_p: is symmetric in its groups",
      round(psa.two_prop_p(30, 100, 10, 100), 9), round(psa.two_prop_p(10, 100, 30, 100), 9))
check("two_prop_p: a wide gap at large n is significant", psa.two_prop_p(30, 100, 10, 100) < 0.01, True)
check("two_prop_p: the same gap at small n is not", psa.two_prop_p(3, 10, 1, 10) > 0.05, True)
# Counts, not percentages: passing 30.0/100.0 as a rate pair must not silently agree.
check("two_prop_p: takes counts, and a 3x gap is not null", psa.two_prop_p(30, 100, 10, 100) < 0.5, True)

check("binom_tail_ge: k<=0 is certain", psa.binom_tail_ge(5, 0, 0.3), 1.0)
check("binom_tail_ge: k>n is impossible", psa.binom_tail_ge(5, 6, 0.3), 0.0)
check("binom_tail_ge: p=1 always reaches n", round(psa.binom_tail_ge(5, 5, 1.0), 6), 1.0)
check("poisson_binomial_tail: certain trials", round(psa.poisson_binomial_tail([1.0, 1.0], 2), 6), 1.0)
check("poisson_binomial_tail: impossible trials", round(psa.poisson_binomial_tail([0.0, 0.0], 1), 6), 0.0)
check("poisson_binomial_tail: fair pair, at least one", round(psa.poisson_binomial_tail([0.5, 0.5], 1), 6), 0.75)
check("poisson_binomial_tail: k beyond the trial count", psa.poisson_binomial_tail([0.5], 5), 0.0)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
