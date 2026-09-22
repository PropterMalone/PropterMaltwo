#!/usr/bin/env python3
# pattern: imperative shell (test harness)
"""Regression tests for mine-runs.py's false-positive accounting.

Pins the false-positive accounting contract:

  1. A finding that is BOTH human `rejected-wrong` AND machine `REFUTED` is
     scored as ONE false positive, not two. (The old code had no `elif`.)
  2. A machine-`REFUTED` finding with no human disposition lands in the
     denominator as well as the numerator, so `fp_rate` can never exceed 1.0.
     (The old code incremented pfp without pdisp.)
  3. Human ruling beats machine verdict. A finding the verifier REFUTED but a
     human then `accepted-mod` and fixed is NOT a false positive — the real case
     is run SYNTHETIC-DISPOSITION-A finding f3, which the old code scored
     against both `rigor` and `rtfm`.

Run: scripts/test_mine_runs_fp.py   (exit 0 = all pass)
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

DIR = Path(__file__).resolve().parent
PASS, FAIL = 0, 0


def check(name, got, want):
    global PASS, FAIL
    if got == want:
        print(f"ok   - {name}")
        PASS += 1
    else:
        print(f"FAIL - {name}\n         got:  {got!r}\n         want: {want!r}")
        FAIL += 1


def make_run(root, run_id, findings, dispositions, verifications):
    """Build a minimal run dir mine-runs.py can read."""
    d = root / run_id
    (d / "verification").mkdir(parents=True, exist_ok=True)
    snap = {
        "version": 2,
        "project": "fixture",
        "mode": "full",
        "findings": findings,
    }
    (d / "findings-snapshot.json").write_text(json.dumps(snap), encoding="utf-8")
    if dispositions is not None:
        (d / "dispositions.json").write_text(json.dumps(dispositions), encoding="utf-8")
    for fid, verdict in verifications.items():
        (d / "verification" / f"{fid}.json").write_text(
            json.dumps({"id": fid, "verdict": verdict, "method": "ran"}), encoding="utf-8"
        )
    return d


def finding(fid, personas, sev="important", verdict=None):
    """A snapshot finding.

    NOTE: mine-runs.py reads the machine verdict from the per-finding
    `verification` key inside findings-snapshot.json, NOT from the
    verification/*.json sidecar files. Fixtures must embed it here or the
    machine channel is silently not exercised.
    """
    f = {"id": fid, "personas": personas, "severity": sev, "title": f"t-{fid}",
         "file": "src/x.ts", "line": 1}
    if verdict:
        f["verification"] = {"verdict": verdict, "method": "ran"}
    return f


def mine(root):
    """Run mine-runs.py over a fixture root, return its JSON payload."""
    out = subprocess.run(
        [sys.executable, str(DIR / "mine-runs.py"), "--runs-dir", str(root), "--json"],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        print("  mine-runs.py stderr:", out.stderr.strip()[:400])
        return None
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        print("  unparseable stdout:", out.stdout.strip()[:400])
        return None


def persona_row(payload, name):
    # `personas` is a dict keyed by persona name, not a list of rows.
    return payload.get("personas", {}).get(name, {})


def main():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        # (1) both human-rejected and machine-REFUTED -> exactly one fp
        make_run(
            root, "20260101T000000Z-aaaaaaaa",
            findings=[finding("f1", ["alpha"], verdict="REFUTED")],
            dispositions={"f1": {"disposition": "rejected-wrong"}},
            verifications={"f1": "REFUTED"},
        )
        # (2) machine-REFUTED only, no human record -> numerator AND denominator
        make_run(
            root, "20260101T000001Z-bbbbbbbb",
            findings=[finding("f1", ["beta"], verdict="REFUTED")],
            dispositions=None,
            verifications={"f1": "REFUTED"},
        )
        # (3) machine-REFUTED but human accepted-mod -> NOT a false positive
        make_run(
            root, "20260101T000002Z-cccccccc",
            findings=[finding("f1", ["gamma"], verdict="REFUTED")],
            dispositions={"f1": {"disposition": "accepted-mod"}},
            verifications={"f1": "REFUTED"},
        )

        payload = mine(root)
        if payload is None:
            print("\nCOULD NOT RUN mine-runs.py against the fixture — see stderr above.")
            print("If the CLI lacks --runs-root/--json, this test needs updating, not the fix.")
            return 2

        a = persona_row(payload, "alpha")
        check("both human+machine -> 1 false positive, not 2", a.get("false_positives"), 1)
        check("both human+machine -> disposed counted once", a.get("disposed"), 1)

        b = persona_row(payload, "beta")
        check("machine-only -> counted in numerator", b.get("false_positives"), 1)
        check("machine-only -> counted in denominator", b.get("disposed"), 1)
        if b.get("disposed"):
            rate = b["false_positives"] / b["disposed"]
            check("machine-only -> fp_rate <= 1.0", rate <= 1.0, True)

        g = persona_row(payload, "gamma")
        check("human accepted-mod beats machine REFUTED (f3 case)", g.get("false_positives"), 0)
        check("human accepted-mod still counted as disposed", g.get("disposed"), 1)

    # --- severity_opinion: REFUTED verdicts are excluded from the tally -------
    # Contract (verifier.md, 2026-08-09): all three enum values presuppose a
    # mechanism that fires, so REFUTED carries no opinion. mine-runs.py filters
    # regardless of what a verdict file claims -- REFUTED is ~6.5% of verdicts,
    # enough to move ADR-14 falsifier (b)'s thresholds at n=50 on a
    # subpopulation where the measurement is meaningless.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        def mk(run_id, verdict, opinion, persona):
            d = root / run_id
            (d / "verification").mkdir(parents=True, exist_ok=True)
            f = finding("f1", [persona])
            f["verification"] = {"verdict": verdict, "method": "ran",
                                 "evidence": "e", "severity_opinion": opinion}
            (d / "findings-snapshot.json").write_text(
                json.dumps({"version": 2, "project": "fx", "mode": "full", "findings": [f]}),
                encoding="utf-8")

        mk("20260101T000010Z-dddddddd", "REFUTED", "too-high", "delta")
        mk("20260101T000011Z-eeeeeeee", "CONFIRMED", "too-high", "epsilon")
        mk("20260101T000012Z-ffffffff", "PLAUSIBLE", "agree", "zeta")

        payload = mine(root)
        if payload is None:
            print("\nCOULD NOT RUN mine-runs.py for the severity_opinion fixture.")
            return 2
        so = lambda p: persona_row(payload, p).get("severity_opinions", {})
        check("REFUTED opinion excluded even when the field is present", so("delta"), {})
        check("CONFIRMED opinion counted", so("epsilon"), {"too-high": 1})
        check("PLAUSIBLE opinion counted", so("zeta"), {"agree": 1})

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
