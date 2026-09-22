#!/usr/bin/env python3
# pattern: imperative shell (test harness)
"""Regression tests for depth-lane-yield.py — ADR-19's falsifier.

Each guard below pins a previously mishandled edge case in the instrument:

  1. **The codex leg voted.** Under ADR-18 every persona gets a Claude leg and a Codex
     leg under the same name. Counting both put every heterogeneous run at exactly 0.50
     purity, failing the strict-majority test, so the forward arm could never populate —
     `pending` forever. `usage.jsonl` carries `backend: codex`; the ballot must use it.
  2. **A set collapsed repeated legs.** Two Claude passes on one model deduped to a single
     vote, so the N=3 escalation attributed identically to N=2. Legs are the unit.
  3. **Arm membership was static.** `future` is in DEPTH_ARM but the standard profile runs
     it on Sonnet, so a control-tier model was counted as depth yield. Membership is
     decided per run from the model that actually ran.
  4. **Silent corpus shrink.** Runs with no snapshot and runs rejected by arm guards
     must be accounted for. Every directory iterated must land in exactly one bucket.
  5. **A malformed field aborted the whole scan.** A non-string `severity` raised
     AttributeError, so one bad snapshot could suppress the instrument entirely.
  6. **`degraded` only saw a fully-missing usage.jsonl**, not one missing depth-arm legs.
  7. **The backward arm had no upper bound**, so a post-retirement `--model-override fable`
     run could join a population labelled "pre-retirement".
  8. **Registered constants must be what this script computes** — the failure ADR-16's
     tombstone records twice, and which this instrument then committed itself.

Run: scripts/test_depth_lane_yield.py   (exit 0 = all pass)
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

DIR = Path(__file__).resolve().parent
SCRIPT = DIR / "depth-lane-yield.py"
PASS, FAIL = 0, 0

_spec = importlib.util.spec_from_file_location("dly", SCRIPT)
dly = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dly)

OPUS, SONNET, FABLE, CODEX = "claude-opus-5[1m]", "claude-sonnet-5[1m]", "claude-fable-5[1m]", "gpt-5.6-sol"


def check(name, got, want):
    global PASS, FAIL
    if got == want:
        print(f"ok   - {name}")
        PASS += 1
    else:
        print(f"FAIL - {name}\n         got:  {got!r}\n         want: {want!r}")
        FAIL += 1


def leg(model, backend="", note=""):
    return {"model": model, "backend": backend, "note": note}


def finding(fid, personas, sev="important"):
    return {"id": fid, "severity": sev, "personas": list(personas)}


def make_run(root, run_id, findings, legs=(), reduced=False, corrupt=False, no_snapshot=False):
    """legs: iterable of (persona, model, backend) written as usage.jsonl persona lines."""
    d = root / run_id
    d.mkdir(parents=True, exist_ok=True)
    if no_snapshot:
        return d
    if corrupt:
        (d / "findings-snapshot.json").write_text("{not json", encoding="utf-8")
        return d
    body = ({"version": 2, "project": "fixture", "criticals": []} if reduced
            else {"version": 2, "project": "fixture", "findings": findings})
    (d / "findings-snapshot.json").write_text(json.dumps(body), encoding="utf-8")
    if legs:
        (d / "usage.jsonl").write_text("\n".join(
            json.dumps({"phase": "persona", "name": p, "model": m, "backend": b})
            for p, m, b in legs) + "\n", encoding="utf-8")
    return d


def run_tool(root, *extra):
    out = subprocess.run([sys.executable, str(SCRIPT), "--runs-dir", str(root), "--json", *extra],
                         capture_output=True, text=True)
    if out.returncode != 0:
        print(out.stderr, file=sys.stderr)
        raise SystemExit(f"tool exited {out.returncode}")
    return json.loads(out.stdout)


# --- 1. the ballot: codex legs must not vote -----------------------------------
HETERO = {p: [leg(OPUS), leg(CODEX, backend="codex")] for p in ("rigor", "coach", "data-int")}
check("ADR-18 heterogeneous N=2 attributes to opus, not mixed",
      dly.attribute(HETERO, set(HETERO)), ("opus", 1.0))
check("N=3 escalation: repeated Claude legs count as legs, not one set element",
      dly.attribute({"rigor": [leg(OPUS), leg(CODEX, backend="codex"), leg(OPUS)]}, {"rigor"}),
      ("opus", 1.0))
check("a genuine Fable/Opus split still attributes by majority",
      dly.attribute({"rigor": [leg(FABLE)], "coach": [leg(FABLE)], "heir": [leg(OPUS)]},
                    {"rigor", "coach", "heir"}), ("fable", 2 / 3))
check("a genuine even split is still unattributable",
      dly.attribute({"rigor": [leg(FABLE)], "heir": [leg(OPUS)]}, {"rigor", "heir"})[0], "mixed")
check("no usable legs -> mixed at zero purity", dly.attribute({}, {"rigor"}), ("mixed", 0.0))
check("a depth lane on Sonnet casts no depth-tier vote",
      dly.attribute({"future": [leg(SONNET), leg(CODEX, backend="codex")]}, {"future"}),
      ("mixed", 0.0))

check("leg_is_usable: codex backend rejected", dly.leg_is_usable(leg(CODEX, backend="codex")), False)
check("leg_is_usable: plain Claude leg accepted", dly.leg_is_usable(leg(OPUS)), True)
check("leg_is_usable: MODEL_MISMATCH rejected",
      dly.leg_is_usable(leg(OPUS, note="MODEL_MISMATCH requested=opus|ran=sonnet")), False)
check("leg_is_usable: FAILED leg rejected", dly.leg_is_usable(leg(OPUS, note="FAILED timeout")), False)
check("leg_is_usable: an unverified alias is still usable",
      dly.leg_is_usable(leg("opus", note="requested=opus|ran=unverified")), True)
check("family: sonnet and haiku are Claude families, not 'other'",
      (dly.family(SONNET), dly.family("claude-haiku-4-5-20251001")), ("sonnet", "haiku"))
check("family: codex is not a Claude family", dly.family(CODEX) in dly.CLAUDE_FAMILIES, False)

# --- 2. EXCLUDED is load-bearing ----------------------------------------------
check("test is excluded from both arms", ("test" in dly.DEPTH_ARM, "test" in dly.CONTROL_ARM),
      (False, False))
check("arms are disjoint", set(dly.DEPTH_ARM) & set(dly.CONTROL_ARM), set())
check("EXCLUDED actually removes from the arms it names",
      set(dly.EXCLUDED) & (set(dly.DEPTH_ARM) | set(dly.CONTROL_ARM)), set())

# --- 3. R arithmetic, per-run membership, degraded ----------------------------
# Backward-mode fixtures need FABLE depth legs — `--backward` filters the Fable arm.
DEPTH3 = [("rigor", FABLE, ""), ("coach", FABLE, ""), ("heir", FABLE, "")]
CTL3 = [("adv", SONNET, ""), ("hyper", SONNET, ""), ("rtfm", SONNET, "")]

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    # depth 6 Imp+ over 3 personas that RAN = 2.0; control 4 over 3 = 1.333; R = 1.5.
    # `heir` ran and scored nothing — a zero, not an absence.
    make_run(root, "20260801T000000Z-a1", [
        *[finding(f"d{i}", ["rigor"]) for i in range(3)],
        *[finding(f"e{i}", ["coach"]) for i in range(3)],
        finding("c1", ["adv"]), finding("c2", ["adv"]), finding("c3", ["hyper"]), finding("c4", ["rtfm"]),
    ], legs=DEPTH3 + CTL3)
    r = run_tool(root, "--backward")
    check("R divides by personas that RAN, not personas that scored", round(r["arm"]["median"], 3), 1.5)
    check("depth arm attributed fable", r["runs"][0]["depth_arm"], "fable")
    check("run is not flagged degraded when depth legs exist", r["runs"][0]["degraded"], False)

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    # A Sonnet-demoted `future` must not enter the depth denominator.
    make_run(root, "20260801T000000Z-a2", [
        finding("d1", ["rigor"]), finding("d2", ["coach"]), finding("d3", ["future"]),
        finding("c1", ["adv"]), finding("c2", ["hyper"]), finding("c3", ["rtfm"]), finding("c4", ["adv"]),
    ], legs=DEPTH3 + CTL3 + [("future", SONNET, "")])
    r = run_tool(root, "--backward")
    check("a Sonnet-demoted depth lane is excluded from the depth denominator",
          r["runs"][0]["depth_personas"], 3)

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    # usage.jsonl exists and records CONTROL legs but no depth legs -> scorer fallback,
    # and the run must say so rather than reporting itself clean.
    make_run(root, "20260801T000000Z-a3", [
        finding("d1", ["rigor"]), finding("d2", ["coach"]),
        finding("c1", ["adv"]), finding("c2", ["hyper"]), finding("c3", ["rtfm"]), finding("c4", ["adv"]),
    ], legs=CTL3)
    r = run_tool(root, "--backward")
    check("a partial usage.jsonl is flagged degraded, not just a missing one",
          r["runs_degraded"], 1)

# --- 4. severity and duplicate attribution -----------------------------------
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    make_run(root, "20260801T000000Z-b1", [
        finding("d1", ["rigor"]), finding("d2", ["coach"], sev="critical"),
        finding("m1", ["rigor"], sev="minor"), finding("n1", ["coach"], sev="noted"),
        finding("t1", ["test"]),
        {"id": "dup", "severity": "important", "personas": ["rigor", "rigor"]},
        finding("c1", ["adv"]), finding("c2", ["hyper"]), finding("c3", ["rtfm"]), finding("c4", ["adv"]),
    ], legs=DEPTH3 + CTL3 + [("test", SONNET, "")])
    row = run_tool(root, "--backward")["runs"][0]
    check("critical and important count; minor and noted do not", row["depth_impplus"], 3)
    check("a duplicated persona attribution counts once", row["depth_personas"], 3)

# --- 5. corpus accounting: nothing vanishes ----------------------------------
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    make_run(root, "20260801T000000Z-c1", [], reduced=True)
    make_run(root, "20260801T000000Z-c2", [], corrupt=True)
    make_run(root, "20260801T000000Z-c3", [], no_snapshot=True)
    make_run(root, "20260801T000000Z-c4", [finding("d1", ["rigor"]), finding("c1", ["adv"])],
             legs=DEPTH3 + CTL3)          # guard-rejected: control arm under MIN_IMPPLUS
    make_run(root, "20260801T000000Z-c5", [
        finding("d1", ["rigor"]), finding("d2", ["coach"]),
        finding("x1", ["adv"]), finding("x2", ["hyper"]), finding("x3", ["rtfm"]), finding("x4", ["adv"]),
    ], legs=DEPTH3 + CTL3)
    r = run_tool(root, "--backward")
    c = r["corpus"]
    check("every directory iterated is accounted for",
          (c["dirs_scanned"], c["dirs_accounted"]), (5, 5))
    check("a run with no snapshot at all is counted, not dropped", c["no_snapshot"], 1)
    check("reduced-shape counted separately from unreadable",
          (c["reduced_shape"], c["unreadable"]), (1, 1))
    check("guard rejections are reported with their reason",
          sum(c["guard_rejected"].values()), 1)
    check("the healthy run is still measured", c["measured"], 1)

# --- 6. a malformed field is quarantined, not fatal --------------------------
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    make_run(root, "20260801T000000Z-d1", [
        {"id": "bad-sev", "severity": 123, "personas": ["rigor"]},
        {"id": "bad-personas", "severity": "important", "personas": "rigor"},
        {"id": "bad-name", "severity": "important", "personas": [42]},
        finding("d1", ["rigor"]), finding("d2", ["coach"]),
        finding("c1", ["adv"]), finding("c2", ["hyper"]), finding("c3", ["rtfm"]), finding("c4", ["adv"]),
    ], legs=DEPTH3 + CTL3)
    r = run_tool(root, "--backward")
    check("a non-string severity does not abort the scan", r["corpus"]["measured"], 1)
    check("every malformed field is reported", len(r["data_issues"]), 3)
    check("the healthy findings in the same run still count", r["runs"][0]["depth_impplus"], 2)
check("norm: non-string returns None, it does not raise", dly.norm(123), None)
check("norm: string normalizes", dly.norm("  Important "), "important")

# --- 7. window bounds --------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    body = [finding("d1", ["rigor"]), finding("d2", ["coach"]),
            finding("c1", ["adv"]), finding("c2", ["hyper"]), finding("c3", ["rtfm"]), finding("c4", ["adv"])]
    FAB = [("rigor", FABLE, ""), ("coach", FABLE, ""), ("heir", FABLE, "")]
    make_run(root, "20260701T000000Z-e1", body, legs=FAB + CTL3)   # before the floor
    make_run(root, "20260715T000000Z-e2", body, legs=FAB + CTL3)   # inside the window
    make_run(root, "20260901T000000Z-e3", body, legs=FAB + CTL3)   # AFTER retirement
    r = run_tool(root, "--backward")
    check("backward arm is bounded below by the floor and above by the retirement date",
          r["arm"]["n"], 1)
    check("a post-retirement Fable override cannot join the baseline population",
          [x["run"] for x in r["runs"]], ["20260715T000000Z-e2"])

# --- 8. thresholds, verdicts, sharpness --------------------------------------
def many(root, n, depth_per_persona, month="08", day0=10, legs=None):
    for i in range(n):
        make_run(root, f"2026{month}{day0+i:02d}T000000Z-{i:08x}",
                 [*[finding(f"d{i}-{j}", ["rigor"]) for j in range(depth_per_persona)],
                  *[finding(f"e{i}-{j}", ["coach"]) for j in range(depth_per_persona)],
                  *[finding(f"c{i}-{j}", [p]) for j, p in enumerate(["adv", "hyper", "rtfm", "adv"])]],
                 legs=(legs or [("rigor", FABLE, ""), ("coach", FABLE, ""), ("heir", FABLE, "")]) + CTL3)

with tempfile.TemporaryDirectory() as td:
    root = Path(td); many(root, 9, 3)
    r = run_tool(root, "--backward")
    check("under MIN_POST_RUNS the verdict is pending, not a pass", r["verdict"], "pending (9/10 runs)")
    check("under MIN_POST_RUNS the powered clause is false", r["clauses"]["powered"], False)

with tempfile.TemporaryDirectory() as td:
    root = Path(td); many(root, 10, 4)   # R = 2d/3 / (4/3) = d/2 = 2.0, above the bar
    r = run_tool(root, "--backward")
    check("a healthy arm at n>=10 reads not met", r["verdict"], "not met")
    check("healthy median is above the threshold", r["arm"]["median"] > dly.THRESHOLD_R, True)

with tempfile.TemporaryDirectory() as td:
    root = Path(td); many(root, 10, 1)   # R = 0.5, below the bar
    r = run_tool(root, "--backward")
    check("a collapsed depth arm FIRES the falsifier", r["verdict"], "FIRED")
    check("every run counted as below threshold", r["runs_below_threshold"], 10)

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    many(root, 5, 4, month="07", day0=11)
    many(root, 5, 1, month="08", day0=10)
    r = run_tool(root, "--backward")
    check("by_month is always emitted", sorted(r["arm"]["by_month"]), ["2026-07", "2026-08"])
    check("by_month separates the eras it exists to expose",
          (r["arm"]["by_month"]["2026-07"], r["arm"]["by_month"]["2026-08"]), (2.0, 0.5))

# --- 9. the forward arm can actually populate under ADR-18 -------------------
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    HET = [("rigor", OPUS, ""), ("rigor", CODEX, "codex"),
           ("coach", OPUS, ""), ("coach", CODEX, "codex"),
           ("heir", OPUS, ""), ("heir", CODEX, "codex")]
    many(root, 3, 3, month="09", day0=1, legs=HET)
    r = run_tool(root)
    check("a heterogeneous post-retirement run reaches the FORWARD arm", r["arm"]["n"], 3)
    check("forward arm attributes opus despite the codex legs",
          {x["depth_arm"] for x in r["runs"]}, {"opus"})

# --- 10. sharpness is computed, not asserted --------------------------------
BASE = [1.0, 2.0, 3.0, 4.0]
check("fire_probability: no loss almost never fires",
      dly.fire_probability(BASE, 1.0, 1.0, 10) < 0.01, True)
check("fire_probability: a collapse almost always fires",
      dly.fire_probability(BASE, 0.1, 1.0, 10) > 0.99, True)
check("fire_probability: rises monotonically as the effect worsens",
      dly.fire_probability(BASE, 0.8, 2.0, 10) <= dly.fire_probability(BASE, 0.4, 2.0, 10), True)
check("fire_probability: empty baseline is unevaluable", dly.fire_probability([], 0.5, 1.0, 10), None)
check("fire_probability: a threshold above everything is certain",
      round(dly.fire_probability(BASE, 1.0, 99.0, 10), 6), 1.0)
check("the report carries the sharpness table", "retain_60pct" in
      run_tool(tempfile.mkdtemp() and Path(tempfile.mkdtemp()))["fire_probability_at_min_runs"], True)

# --- 11. the registered constants are what this script computes -------------
check("threshold is the baseline scaled by 0.60, not a round number",
      round(dly.BASELINE_MEDIAN * 0.60, 2), dly.THRESHOLD_R)
check("retirement date is the ADR-18 partition marker too", dly.RETIREMENT_DATE, "2026-08-26")
check("baseline floor precedes the retirement date", dly.BASELINE_FLOOR < dly.RETIREMENT_DATE, True)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
