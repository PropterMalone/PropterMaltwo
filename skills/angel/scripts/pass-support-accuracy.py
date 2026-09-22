#!/usr/bin/env python3
# pattern: imperative shell
"""Test whether multiball pass support predicts over-filed severity.

ADR-16 removed frequency-based singleton demotion below N=5. This instrument
compares findings with singleton versus corroborated pass support.

A verdict is over-filed when the verifier REFUTED the mechanism or retained it
with `severity_opinion: too-high`. Missing opinions do not imply agreement, and
verifier-failure stubs are excluded.

Results are stratified by support, filed severity, and multiball N. Verification
admission and queue caps can select findings by severity and corroboration, so
the Critical stratum is a weaker-confound check rather than a clean control.
`p_value` is diagnostic only; the registered firing rule uses point-estimate
thresholds defined below and documented in ADR-16.

Usage: pass-support-accuracy.py [--runs-dir DIR] [--since YYYY-MM-DD] [--json]
"""
import argparse
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # runs as __main__ from any CWD
from angel_corpus import in_scope, load_snapshot, run_date

# ADR-14 shipped `severity_opinion` as a required verdict field on this date. Runs before
# it cannot distinguish "verifier agreed" from "no such field existed".
SEVERITY_OPINION_FLOOR = "2026-08-09"

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TERMINAL_VERDICTS = ("CONFIRMED", "PLAUSIBLE", "REFUTED")
SEVERITIES = ("critical", "important", "minor", "noted")
OPINIONS = ("agree", "too-high", "too-low")

# Pre-registered thresholds. See ADR-16 for the derivation of each; changing a value here
# without amending the ADR breaks the pre-registration these numbers exist to provide.
MIN_N_SINGLETON = 100
MIN_N_CORROBORATED = 75
ABS_RATE_PCT = 25.0       # see the per-run noise baseline in the report before reading a crossing as signal
RATIO = 2.0
# A run needs at least this many judged singletons before its per-run rate is quotable.
# Below it the rate is too coarsely quantized to interpret as a stable run-level signal.
MIN_RUN_SINGLETONS = 4


def binom_tail_ge(n, k, p):
    """P(X >= k) for X ~ Bin(n, p)."""
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1))


def poisson_binomial_tail(probs, k):
    """P(at least k successes) among independent Bernoulli trials with differing probs."""
    dist = [1.0]
    for p in probs:
        nxt = [0.0] * (len(dist) + 1)
        for i, d in enumerate(dist):
            nxt[i] += d * (1 - p)
            nxt[i + 1] += d * p
        dist = nxt
    return sum(dist[k:]) if k < len(dist) else 0.0


def classify(finding, issues):
    """-> (k, N, over_filed, severity) for a countable finding, else None.

    Countable means: multiball (some persona ran N>=2 passes), carries a terminal verdict,
    and a severity judgment was actually rendered. Malformed rows are appended to `issues`
    rather than silently dropped — a corrupt row that vanishes quietly is indistinguishable
    from one that never existed, and this instrument's denominators are load-bearing.
    """
    if not isinstance(finding, dict):
        return None
    verif = finding.get("verification")
    if not isinstance(verif, dict):
        return None
    verdict = (verif.get("verdict") or "").strip().upper()
    if verdict not in TERMINAL_VERDICTS:
        return None

    opinion = verif.get("severity_opinion")
    if opinion is not None:
        if not isinstance(opinion, str):
            issues.append((finding.get("id"), f"severity_opinion not a string: {opinion!r}"))
            return None
        opinion = opinion.strip().lower()
        if opinion and opinion not in OPINIONS:
            # An unrecognized value is not assent. Counting it as `agree` — which a bare
            # `opinion == "too-high"` test does — silently pads the denominator.
            issues.append((finding.get("id"), f"unrecognized severity_opinion: {opinion!r}"))
            return None
    # REFUTED carries no severity_opinion by contract (verifier.md) and needs none —
    # refutation IS the severity judgment. Any other verdict without the field had no
    # judgment rendered and must not be read as agreement.
    if verdict != "REFUTED" and not opinion:
        return None

    ps = finding.get("pass_support")
    if not isinstance(ps, dict):
        return None
    pairs = []
    for persona, t in ps.items():
        if not (isinstance(t, (list, tuple)) and len(t) == 2):
            continue
        k, n = t
        if not (isinstance(k, int) and isinstance(n, int)) or isinstance(k, bool) or isinstance(n, bool):
            # Comparing a str to an int raises and aborts the entire scan, not just this row.
            issues.append((finding.get("id"), f"non-integer pass_support for {persona!r}: {t!r}"))
            continue
        pairs.append((k, n))
    if not any(n >= 2 for _k, n in pairs):
        return None  # not a multiball finding; k is meaningless

    severity = (finding.get("severity") or "").strip().lower()
    if severity not in SEVERITIES:
        issues.append((finding.get("id"), f"severity outside the enum: {severity!r}"))
        return None

    # k floored at 1 for personas whose passes failed to rid-match (assemble-wpr.py's
    # best_rid join), so max() is a lower bound on corroboration — this dilutes the k=1
    # stratum with genuinely corroborated findings and biases the ratio DOWN, against firing.
    k = max(k for k, _n in pairs)
    n = max(n for _k, n in pairs)
    over_filed = verdict == "REFUTED" or opinion == "too-high"
    return k, n, over_filed, severity


def tally(rows):
    """rows of (k, over_filed) -> {'k1': [over, n], 'k2': [over, n]}"""
    out = {"k1": [0, 0], "k2": [0, 0]}
    for k, over in rows:
        b = out["k1"] if k == 1 else out["k2"]
        b[1] += 1
        b[0] += bool(over)
    return out


def rates(t):
    (o1, n1), (o2, n2) = t["k1"], t["k2"]
    r1 = 100.0 * o1 / n1 if n1 else None
    r2 = 100.0 * o2 / n2 if n2 else None
    if r1 is None or r2 is None:
        ratio = None            # a stratum is empty: unevaluable, not "no effect"
    elif r2 == 0:
        # The strongest possible signal for the hypothesis — zero over-filing among
        # corroborated findings. A falsity test that treats this as unevaluable can
        # never fire on its own best evidence.
        ratio = math.inf if r1 > 0 else None
    else:
        ratio = r1 / r2
    return o1, n1, r1, o2, n2, r2, ratio


def two_prop_p(o1, n1, o2, n2):
    """Two-sided z-test p-value for a difference of proportions; None when undefined.

    Diagnostic only — the firing rule never gates on it. See the module docstring.
    """
    if not n1 or not n2:
        return None
    p1, p2 = o1 / n1, o2 / n2
    pbar = (o1 + o2) / (n1 + n2)
    se = math.sqrt(pbar * (1 - pbar) * (1 / n1 + 1 / n2))
    if se == 0:
        return None
    z = (p1 - p2) / se
    return math.erfc(abs(z) / math.sqrt(2))


def per_run_noise(per_run, base_rate_pct, threshold_pct):
    """Expected threshold crossings by chance at the pooled base rate.

    Small per-run denominators quantize rates coarsely. Reporting the null
    expectation beside observed crossings prevents noise from being mistaken
    for evidence that a threshold is reachable or meaningful.
    """
    runs = [(name, o, n) for name, (o, n) in sorted(per_run.items()) if n >= MIN_RUN_SINGLETONS]
    if not runs or base_rate_pct is None:
        return None
    p = base_rate_pct / 100.0
    t = threshold_pct / 100.0
    probs, observed = [], 0
    for _name, o, n in runs:
        need = math.ceil(t * n - 1e-9)
        probs.append(binom_tail_ge(n, need, p))
        if 100.0 * o / n >= threshold_pct:
            observed += 1
    return {
        "runs_quotable": len(runs),
        "min_singletons": MIN_RUN_SINGLETONS,
        "observed_at_or_above": observed,
        "expected_by_chance": sum(probs),
        "p_at_least_observed": poisson_binomial_tail(probs, observed),
        "max_rate_pct": max(100.0 * o / n for _name, o, n in runs),
    }


def fmt(o, n, r):
    return f"{o}/{n} = {r:5.1f}%" if r is not None else f"{o}/{n} = —"


def fmt_ratio(r):
    if r is None:
        return "—"
    return "inf" if math.isinf(r) else f"{r:.2f}x"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-dir", default=str(Path.home() / ".angel" / "runs"))
    ap.add_argument("--since", default=SEVERITY_OPINION_FLOOR,
                    help=f"YYYY-MM-DD floor, inclusive (default {SEVERITY_OPINION_FLOOR}, "
                         "when severity_opinion became required)")
    ap.add_argument("--json", action="store_true", help="emit machine JSON instead of a report")
    args = ap.parse_args()

    if not DATE_RE.match(args.since):
        # Validate before lexical comparison so malformed input cannot silently
        # skip all runs and produce a clean-looking empty result.
        print(f"--since must be YYYY-MM-DD, got {args.since!r}", file=sys.stderr)
        sys.exit(2)

    runs_dir = Path(args.runs_dir)
    if not runs_dir.is_dir():
        print(f"no runs dir: {runs_dir}", file=sys.stderr)
        sys.exit(1)

    pooled, by_sev, by_n = [], defaultdict(list), defaultdict(list)
    per_run_k1 = defaultdict(lambda: [0, 0])
    scanned = in_scope_n = undatable = 0
    unreadable, data_issues = [], []

    for rd in sorted(d for d in runs_dir.iterdir() if d.is_dir()):
        data, _name, errors = load_snapshot(rd)
        unreadable.extend(errors)
        if data is None:
            continue
        scanned += 1
        date = run_date(data, rd)
        if not in_scope(date, args.since):
            undatable += date == "????-??-??"
            continue
        in_scope_n += 1
        for f in data["findings"]:
            got = classify(f, data_issues)
            if got is None:
                continue
            k, n, over, sev = got
            pooled.append((k, over))
            by_sev[sev].append((k, over))
            by_n[n].append((k, over))
            if k == 1:
                per_run_k1[rd.name][1] += 1
                per_run_k1[rd.name][0] += bool(over)

    o1, n1, r1, o2, n2, r2, ratio = rates(tally(pooled))
    crit = rates(tally(by_sev["critical"]))
    imp = rates(tally(by_sev["important"]))

    powered = n1 >= MIN_N_SINGLETON and n2 >= MIN_N_CORROBORATED
    abs_met = r1 is not None and r1 >= ABS_RATE_PCT
    ratio_met = ratio is not None and ratio >= RATIO
    # Weaker-confound guard. Criticals are admitted to the verify queue regardless of k,
    # so their stratum carries less of the rule-2 selection effect than the Importants —
    # but the queue cap re-introduces corroboration selection, so this is a sanity check,
    # not a clean read (see the module docstring). An EMPTY Critical stratum is
    # unevaluable, not passing: without a denominator there is no check to have survived.
    crit_evaluable = crit[1] > 0 and crit[4] > 0
    uncontradicted = crit_evaluable and crit[6] is not None and crit[6] >= 1.0
    fired = bool(powered and abs_met and ratio_met and uncontradicted)

    noise = per_run_noise(per_run_k1, r1, ABS_RATE_PCT)
    result = {
        "since": args.since,
        "runs_scanned": scanned,
        "runs_in_scope": in_scope_n,
        "runs_undatable_excluded": undatable,
        "snapshots_unreadable": [{"path": str(p), "reason": why} for p, why in unreadable],
        "data_issues": [{"finding": fid, "reason": why} for fid, why in data_issues],
        "singleton": {"over_filed": o1, "n": n1, "pct": r1},
        "corroborated": {"over_filed": o2, "n": n2, "pct": r2},
        "ratio": ratio,
        "p_value": two_prop_p(o1, n1, o2, n2),
        "p_value_note": "diagnostic only — the firing rule never gates on it",
        "by_severity": {
            s: {"k1": v[:3], "k2": v[3:6], "ratio": v[6]}
            for s, v in (("critical", crit), ("important", imp))
        },
        "by_multiball_n": {
            str(n): {"k1": v[:3], "k2": v[3:6], "ratio": v[6]}
            for n, v in ((n, rates(tally(rows))) for n, rows in sorted(by_n.items()))
        },
        "per_run_k1": {name: {"over_filed": o, "n": n} for name, (o, n) in sorted(per_run_k1.items())},
        "per_run_noise_baseline": noise,
        "clauses": {
            "powered": powered, "absolute": abs_met,
            "ratio": ratio_met, "uncontradicted": uncontradicted,
            "critical_stratum_evaluable": crit_evaluable,
        },
        "verdict": "FIRED" if fired else "not met",
    }

    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    p = result["p_value"]
    print(f"ADR-16 falsifier — over-filed rate by pass support (since {args.since})")
    print(f"  runs scanned {scanned}, in scope {in_scope_n}"
          + (f", undatable excluded {undatable}" if undatable else ""))
    if unreadable:
        print(f"  !! {len(unreadable)} unreadable snapshot(s) — corpus is incomplete:")
        for path, why in unreadable[:5]:
            print(f"       {path}: {why}")
    if data_issues:
        print(f"  !! {len(data_issues)} malformed finding(s) excluded:")
        for fid, why in data_issues[:5]:
            print(f"       {fid}: {why}")
    print()
    print(f"  k=1  singleton    : over-filed {fmt(o1, n1, r1)}")
    print(f"  k>=2 corroborated : over-filed {fmt(o2, n2, r2)}")
    print(f"  ratio             : {fmt_ratio(ratio)}")
    print(f"  two-sided p       : {p:.3f} (diagnostic; never gated on)" if p is not None
          else "  two-sided p       : —")
    print()
    print("  by severity (Criticals are less k-selected than Importants — not unselected):")
    for label, s in (("critical ", crit), ("important", imp)):
        print(f"    {label} k=1 {fmt(s[0], s[1], s[2])}   k>=2 {fmt(s[3], s[4], s[5])}   ratio {fmt_ratio(s[6])}")
    print()
    print("  by multiball N (the restoration rule is N-specific; pooling hides sign flips):")
    for n, rows in sorted(by_n.items()):
        s = rates(tally(rows))
        print(f"    N={n}        k=1 {fmt(s[0], s[1], s[2])}   k>=2 {fmt(s[3], s[4], s[5])}   ratio {fmt_ratio(s[6])}")
    if noise:
        print()
        print(f"  per-run crossings of {ABS_RATE_PCT}% (runs with >= {MIN_RUN_SINGLETONS} judged singletons):")
        print(f"    observed {noise['observed_at_or_above']} of {noise['runs_quotable']}"
              f", expected by chance {noise['expected_by_chance']:.2f}"
              f", P(>= observed) {noise['p_at_least_observed']:.2f}"
              f", max {noise['max_rate_pct']:.1f}%")
    print()
    c = result["clauses"]
    print(f"  [{'x' if c['powered'] else ' '}] powered        n1>={MIN_N_SINGLETON} and n2>={MIN_N_CORROBORATED}  (have {n1}, {n2})")
    print(f"  [{'x' if c['absolute'] else ' '}] absolute       k=1 rate >= {ABS_RATE_PCT}%")
    print(f"  [{'x' if c['ratio'] else ' '}] ratio          k=1/k>=2 >= {RATIO}x")
    print(f"  [{'x' if c['uncontradicted'] else ' '}] uncontradicted Critical stratum ratio >= 1.0x"
          + ("" if crit_evaluable else "  (UNEVALUABLE — empty stratum, cannot pass)"))
    print()
    print(result["verdict"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
