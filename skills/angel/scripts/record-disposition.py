#!/usr/bin/env python3
# pattern: imperative shell
"""Upsert a per-finding disposition into <run_dir>/dispositions.json.

Disposition is the precision signal: `rejected-wrong` marks a false positive;
every other value means the finding was valid (acted-on, low-value-but-correct,
or deferred). Consumed by mine-runs.py to compute per-persona precision — so a
noisy persona and a sharp one stop looking identical in the value table. Called
from both the manual-apply path and --fix-last (SKILL.md §9a / §10), which is
how the old fix-last-only asymmetry gets closed.

Usage: record-disposition.py <run_dir> <finding_id> <disposition> [note]
  disposition: accepted | accepted-mod | rejected-wrong | rejected-low | deferred
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

VALID = {"accepted", "accepted-mod", "rejected-wrong", "rejected-low", "deferred"}


def main():
    if len(sys.argv) < 4:
        sys.exit("usage: record-disposition.py <run_dir> <finding_id> <disposition> [note]\n"
                 f"  disposition: {' | '.join(sorted(VALID))}")
    run_dir = Path(sys.argv[1])
    fid = sys.argv[2]
    disp = sys.argv[3]
    note = " ".join(sys.argv[4:]) if len(sys.argv) > 4 else ""  # join, don't drop unquoted words

    if disp not in VALID:
        sys.exit(f"invalid disposition '{disp}'; one of: {', '.join(sorted(VALID))}")
    if not run_dir.is_dir():
        sys.exit(f"run dir not found: {run_dir}")
    # Refuse to write outside the runs root (path-traversal guard; override for tests).
    runs_root = Path(os.environ.get("ANGEL_RUNS_ROOT", str(Path.home() / ".angel" / "runs"))).resolve()
    resolved = run_dir.resolve()
    if resolved != runs_root and runs_root not in resolved.parents:
        sys.exit(f"refusing to write outside runs root {runs_root}: {run_dir}")

    p = run_dir / "dispositions.json"
    data = {}
    if p.is_file():
        try:
            loaded = json.loads(p.read_text())
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            data = {}

    data[fid] = {
        "disposition": disp,
        "note": note,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    p.write_text(json.dumps(data, indent=2) + "\n")
    print(f"recorded {fid} -> {disp} in {p}")


if __name__ == "__main__":
    main()
