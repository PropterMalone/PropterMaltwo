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
    record = {k: e.get(k) for k in keys}
    if "backend" in e:
        record["backend"] = e["backend"]
    return record


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
    by_backend = {}
    for entry in entries:
        tokens = entry.get("total_tokens")
        if tokens is None:
            continue
        backend = entry.get("backend") or "claude-agent"
        by_backend[backend] = by_backend.get(backend, 0) + tokens

    reader = next((x for x in entries if x.get("phase") == "reader"), None)
    # Pick the last integrator entry that has no STALLED/KILLED note; fall back to
    # last entry overall. A stalled/killed first attempt logged before a delivered
    # second attempt must not corrupt model-attribution data (f22).
    integrator_entries = [x for x in entries if x.get("phase") == "integrator"]
    integrator = None
    if integrator_entries:
        delivered = [x for x in integrator_entries
                     if (x.get("note") or "").upper() not in ("STALLED", "KILLED")]
        integrator = delivered[-1] if delivered else integrator_entries[-1]
    reconciler_entries = [x for x in entries if x.get("phase") == "reconciler"]
    verifier_entries = [x for x in entries if x.get("phase") == "verifier"]

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

    # Read the reviewed project's git HEAD from PROJECT_COMMIT (written by init-run.sh).
    # "null" (string) means non-git or git unavailable; absent file means unknown (pre-f34).
    project_commit_path = Path(run_dir) / "PROJECT_COMMIT"
    if project_commit_path.is_file():
        raw = project_commit_path.read_text().strip()
        project_commit = None if raw == "null" else (raw or None)
    else:
        project_commit = None

    # Review scale is needed to distinguish yield changes from changes in target
    # size. Both inputs already exist in every run dir, so this needs no extra
    # orchestrator step: filelist.txt is written for full mode, src-only.diff for diff.
    def _scale(run_dir):
        d = Path(run_dir)
        files = diff_lines = None
        fl = d / "filelist.txt"
        if fl.is_file():
            files = sum(1 for ln in fl.read_text(errors="replace").splitlines() if ln.strip())
        for name in ("src-only.diff", "review.diff"):
            p = d / name
            if p.is_file():
                n = 0
                for ln in p.read_text(errors="replace").splitlines():
                    # count content lines only; +++/--- are file headers
                    if (ln.startswith("+") or ln.startswith("-")) and not ln.startswith(("+++", "---")):
                        n += 1
                diff_lines = n
                break
        if files is None and diff_lines is None:
            return None
        return {"files": files, "diff_lines": diff_lines}

    scale = _scale(run_dir)

    return {
        "run_dir": str(run_dir),
        "project": snapshot.get("project"),
        "mode": snapshot.get("mode"),
        "reader_enabled": reader is not None,
        "started_at": started_at,
        "ended_at": ended_at,
        "totals": {
            "total_tokens": total_tokens,
            "by_backend": by_backend,
            "wall_seconds": wall_seconds,
            "reader": phase_record(reader, ("total_tokens", "duration_ms", "tool_uses")) if reader else None,
            "personas": [
                phase_record(x, ("name", "model", "total_tokens", "duration_ms", "reader_pack", "tool_uses"))
                for x in entries
                if x.get("phase") == "persona"
            ],
            "integrator": phase_record(
                integrator,
                ("model", "total_tokens", "duration_ms", "tool_uses",
                 "initial_context_tokens", "peak_context_tokens", "input_tokens",
                 "output_tokens", "request_count", "turn_count"),
            ) if integrator else None,
            "reconcilers": [
                phase_record(x, ("name", "model", "total_tokens", "duration_ms", "tool_uses"))
                for x in reconciler_entries
            ],
            "verifiers": [
                phase_record(x, ("name", "model", "total_tokens", "duration_ms", "tool_uses"))
                for x in verifier_entries
            ],
        },
        "unmeasured": unmeasured,
        "skill_commit": None,  # filled by the shell
        "project_commit": project_commit,
        "scale": scale,
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
