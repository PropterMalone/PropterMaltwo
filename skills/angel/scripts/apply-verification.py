#!/usr/bin/env python3
# pattern: imperative shell (I/O); patch + summary rendering in the FUNCTIONAL CORE block
"""Fold verifier verdicts back into a run's findings snapshot — verification v1.

After the integrator writes findings-snapshot.json (top-level `verify_queue`,
per-finding `"verification": null`), the orchestrator dispatches verifier
subagents and writes each verdict to $RUN_DIR/verification/{finding_id}.json:

  {"id":"f3","verdict":"CONFIRMED|PLAUSIBLE|REFUTED","method":"ran|traced",
   "evidence":"<=300 chars why","severity_opinion":"agree|too-high|too-low",
   "note":"optional"}

This script applies them: patches each matching finding's `verification`
field, emits $RUN_DIR/verification-summary.md (REFUTED first), and replaces-
or-appends the same `## Verification` section in $RUN_DIR/report.md.

Verification is NOT gated in v1: zero verdict files is a clean no-op (exit 0),
unknown finding ids warn to stderr and continue, findings without verdicts
keep `verification: null`. Idempotent: a second run leaves the snapshot
byte-identical and never duplicates the report section.

Usage: apply-verification.py <RUN_DIR>
"""
import json
import os
import re
import sys
from pathlib import Path

FINDING_ID_RE = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')

SECTION_HEADING = "## Verification"
VALID_VERDICTS = ("CONFIRMED", "PLAUSIBLE", "REFUTED")
ALL_CRITICALS_REFUTED = ("⚠ All verified Criticals were REFUTED — the verdict line "
                         "may overstate; human downgrade suggested.")


# ============================ FUNCTIONAL CORE ============================
# Pure: no I/O. Snapshot findings + verdict dicts -> patched findings,
# summary markdown, patched report text.

def patch_findings(findings, verdicts_by_id):
    """Set each matching finding's `verification` field in place.

    Returns the verdict ids that matched no finding (caller warns)."""
    known = set()
    for f in findings:
        if not isinstance(f, dict):
            continue
        known.add(f.get("id"))
        v = verdicts_by_id.get(f.get("id"))
        if v:
            f["verification"] = {k: v.get(k) for k in ("verdict", "method", "evidence")}
            # severity_opinion rides along so severity accuracy is computable from
            # the snapshot alone. Written ONLY when the verdict carries it: a
            # `severity_opinion: null` on every historical-shaped record would make
            # "no opinion" and "opinion absent" indistinguishable downstream.
            if v.get("severity_opinion"):
                f["verification"]["severity_opinion"] = v["severity_opinion"]
    return [fid for fid in verdicts_by_id if fid not in known]


def render_summary(findings, verdicts_by_id):
    """The `## Verification` markdown section — one line per applied verdict.

    REFUTED lines come first under a bold warning so a refuted Critical can't
    hide below the fold; within each group, snapshot order (deterministic, so
    the section is byte-stable across re-runs)."""
    rows = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        v = verdicts_by_id.get(f.get("id"))
        if v:
            rows.append((f, v))

    refuted = [r for r in rows if r[1].get("verdict") == "REFUTED"]
    rest = [r for r in rows if r[1].get("verdict") != "REFUTED"]

    lines = [SECTION_HEADING, ""]
    if refuted:
        lines += [f"**⚠ {len(refuted)} of {len(rows)} verified finding(s) REFUTED:**", ""]
    for f, v in refuted + rest:
        lines.append(f"- **{v.get('verdict')}** {f.get('id')} ({f.get('severity')}) "
                     f"— {f.get('title')} — {v.get('evidence')}")

    # Every Critical carries a REFUTED verdict (an unverified Critical still
    # counts as non-refuted, so it blocks the warning) -> the run-level verdict
    # was driven by findings verification threw out.
    crits = [f for f in findings
             if isinstance(f, dict) and f.get("severity") == "critical"]
    if crits and all(verdicts_by_id.get(f.get("id"), {}).get("verdict") == "REFUTED"
                     for f in crits):
        lines += ["", ALL_CRITICALS_REFUTED]
    return "\n".join(lines) + "\n"


def patch_report(report_text, section):
    """Replace an existing `## Verification` section, else append one.

    A section runs from its heading to the next `## ` heading (or EOF) —
    replace-not-duplicate is what makes a re-run idempotent on report.md."""
    lines = report_text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.strip() == SECTION_HEADING), None)
    if start is None:
        return report_text.rstrip("\n") + "\n\n---\n\n" + section
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
               len(lines))
    return "\n".join(lines[:start] + section.rstrip("\n").splitlines() + lines[end:]) + "\n"


# ============================ IMPERATIVE SHELL ============================

def atomic_write(path, text):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def load_verdicts(verdict_files):
    verdicts_by_id = {}
    for vf in verdict_files:
        try:
            v = json.loads(vf.read_text())
        except Exception as e:
            print(f"warning: skipping malformed verdict {vf.name}: {e}", file=sys.stderr)
            continue
        fid = v.get("id") if isinstance(v, dict) else None
        if not fid:
            print(f"warning: verdict {vf.name} has no finding id, skipped", file=sys.stderr)
            continue
        if not FINDING_ID_RE.match(fid):
            print(f"warning: verdict {vf.name} finding id {fid!r} fails charset check "
                  f"(must match ^[a-zA-Z0-9_-]{{1,64}}$), invalid — skipped", file=sys.stderr)
            continue
        if v.get("verdict") not in VALID_VERDICTS:
            print(f"warning: verdict {vf.name} has invalid verdict "
                  f"{v.get('verdict')!r}, skipped", file=sys.stderr)
            continue
        verdicts_by_id[fid] = v
    return verdicts_by_id


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: apply-verification.py <RUN_DIR>")
    run_dir = Path(sys.argv[1])
    if not run_dir.is_dir():
        sys.exit(f"run dir not found: {run_dir}")

    # Refuse to write outside the runs root (path-traversal guard; override for tests).
    runs_root = Path(os.environ.get("ANGEL_RUNS_ROOT", str(Path.home() / ".angel" / "runs"))).resolve()
    resolved = run_dir.resolve()
    if resolved != runs_root and runs_root not in resolved.parents:
        sys.exit(f"refusing to write outside runs root {runs_root}: {run_dir}")

    vdir = run_dir / "verification"
    verdict_files = sorted(vdir.glob("*.json")) if vdir.is_dir() else []
    if not verdict_files:
        print("no verdicts to apply")
        return

    snap_path = run_dir / "findings-snapshot.json"
    if not snap_path.is_file():
        sys.exit(f"findings-snapshot.json not found: {snap_path}")
    try:
        snap = json.loads(snap_path.read_text())
    except Exception as e:
        sys.exit(f"unparseable findings-snapshot.json: {e}")
    findings = snap.get("findings") if isinstance(snap, dict) else None
    if not isinstance(findings, list):
        sys.exit(f"no findings list in {snap_path}")

    verdicts_by_id = load_verdicts(verdict_files)
    unknown = patch_findings(findings, verdicts_by_id)
    for fid in unknown:
        print(f"warning: verdict for unknown finding id {fid!r} — "
              "no such finding in snapshot", file=sys.stderr)

    atomic_write(snap_path, json.dumps(snap, indent=2) + "\n")

    section = render_summary(findings, verdicts_by_id)
    atomic_write(run_dir / "verification-summary.md", section)

    report_path = run_dir / "report.md"
    if report_path.is_file():
        atomic_write(report_path, patch_report(report_path.read_text(), section))

    applied = len(verdicts_by_id) - len(unknown)
    print(f"applied {applied} verdict(s) ({len(unknown)} unknown-id) -> "
          f"{snap_path.name}, verification-summary.md"
          + (", report.md" if report_path.is_file() else ""))


if __name__ == "__main__":
    main()
