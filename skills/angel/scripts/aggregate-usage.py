#!/usr/bin/env python3
# pattern: imperative shell (I/O); pure aggregation in the FUNCTIONAL CORE block
"""Aggregate a run's usage.jsonl into usage.json — SKILL.md §8a, mechanized.

The authoritative generator of usage.json. Hand-assembling it in the
orchestrator is the same failure class already root-caused for the usage.log
line (see append-usage-log.sh header): LLM hand-formatting drifts. This makes
the §8a schema a mechanical guarantee instead of a discipline.

Usage: aggregate-usage.py <RUN_DIR>
Reads  $RUN_DIR/usage.jsonl (+ findings-snapshot.json if present).
Writes $RUN_DIR/usage.json, and $RUN_DIR/UNMEASURED.md when any dispatch
came back with total_tokens null.
"""
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SEVERITIES = ("critical", "important", "minor", "noted")


# ============================ FUNCTIONAL CORE ============================
# Pure: no I/O. jsonl entries + snapshot dict + run-dir name -> usage.json dict.

def parse_iso(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def basename_started_at(run_dir_name):
    m = re.match(r"^(\d{8}T\d{6}Z)", run_dir_name)
    if not m:
        return None
    try:
        dt = datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ")
    except ValueError:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def phase_record(e, keys):
    return {k: e.get(k) for k in keys}


def aggregate(entries, run_dir, snapshot):
    started_at = basename_started_at(Path(run_dir).name)
    if started_at is None:
        starts = sorted(e["started_at"] for e in entries if e.get("started_at"))
        started_at = starts[0] if starts else None
    ends = sorted(e["ended_at"] for e in entries if e.get("ended_at"))
    ended_at = ends[-1] if ends else None

    wall_seconds = None
    s, e = parse_iso(started_at), parse_iso(ended_at)
    if s and e:
        wall_seconds = int((e - s).total_seconds())

    measured = [x["total_tokens"] for x in entries if x.get("total_tokens") is not None]
    total_tokens = sum(measured) if measured else None

    reader = next((x for x in entries if x.get("phase") == "reader"), None)
    integrator = next((x for x in entries if x.get("phase") == "integrator"), None)

    unmeasured = [
        f"{x.get('phase', '?')}:{x.get('name', '?')}"
        for x in entries
        if x.get("total_tokens") is None
    ]

    snapshot = snapshot or {}
    findings = {sev: 0 for sev in SEVERITIES}
    for f in snapshot.get("findings", []):
        sev = f.get("severity")
        if sev in findings:
            findings[sev] += 1

    return {
        "run_dir": str(run_dir),
        "project": snapshot.get("project"),
        "mode": snapshot.get("mode"),
        "reader_enabled": reader is not None,
        "started_at": started_at,
        "ended_at": ended_at,
        "totals": {
            "total_tokens": total_tokens,
            "wall_seconds": wall_seconds,
            "reader": phase_record(reader, ("total_tokens", "duration_ms", "tool_uses")) if reader else None,
            "personas": [
                phase_record(x, ("name", "model", "total_tokens", "duration_ms", "reader_pack", "tool_uses"))
                for x in entries
                if x.get("phase") == "persona"
            ],
            "integrator": phase_record(integrator, ("model", "total_tokens", "duration_ms", "tool_uses")) if integrator else None,
        },
        "unmeasured": unmeasured,
        "skill_commit": None,  # filled by the shell
        "verdict": snapshot.get("verdict"),
        "findings": findings,
    }


# ============================ IMPERATIVE SHELL ============================

def skill_commit():
    skill_root = Path(__file__).resolve().parent.parent
    try:
        out = subprocess.run(
            ["git", "-C", str(skill_root), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip() if out.returncode == 0 else None
    except OSError:
        return None


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: aggregate-usage.py <RUN_DIR>")
    run_dir = Path(sys.argv[1]).resolve()
    jsonl = run_dir / "usage.jsonl"
    if not jsonl.is_file():
        sys.exit(f"no usage.jsonl in {run_dir}")

    entries = []
    for line in jsonl.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            print(f"warning: skipping malformed jsonl line: {line[:80]}", file=sys.stderr)

    snapshot = None
    snap_path = run_dir / "findings-snapshot.json"
    if snap_path.is_file():
        try:
            snapshot = json.loads(snap_path.read_text())
        except json.JSONDecodeError:
            print("warning: findings-snapshot.json malformed; project/verdict/findings null", file=sys.stderr)

    usage = aggregate(entries, run_dir, snapshot)
    usage["skill_commit"] = skill_commit()

    (run_dir / "usage.json").write_text(json.dumps(usage, indent=2) + "\n")
    if usage["unmeasured"]:
        (run_dir / "UNMEASURED.md").write_text(
            "# Unmeasured dispatches\n\nToken totals in usage.json/usage.log are partial — "
            "these dispatches came back with total_tokens null:\n\n"
            + "\n".join(f"- {u}" for u in usage["unmeasured"]) + "\n"
        )
    print(f"wrote {run_dir / 'usage.json'}"
          + (f" ({len(usage['unmeasured'])} unmeasured)" if usage["unmeasured"] else ""))


if __name__ == "__main__":
    main()
