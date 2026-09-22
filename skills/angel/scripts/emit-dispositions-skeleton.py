#!/usr/bin/env python3
# pattern: imperative shell
"""Emit a skeleton dispositions.json — every finding starts as "no-record".

Sparse disposition records make untriaged and unseen findings indistinguishable.
The skeleton makes non-triage explicit: every
finding id from findings-snapshot.json gets a "no-record" placeholder entry
in record-disposition.py's exact schema, so later recording upserts in place.
If an EXPERIMENT marker file exists in the run dir, a top-level
`"experiment": true` field tags the run, so an untriaged Critical from an
experiment run is distinguishable from a neglected live ship-blocker.

Idempotent: never touches an existing dispositions.json. Called as the last
finalize-run.sh stage (after the completeness gate).

Usage: emit-dispositions-skeleton.py <run_dir>
"""
import json
import os
import re
import sys
from pathlib import Path

FINDING_ID_RE = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: emit-dispositions-skeleton.py <run_dir>")
    run_dir = Path(sys.argv[1])
    if not run_dir.is_dir():
        sys.exit(f"run dir not found: {run_dir}")
    # Refuse to write outside the runs root (path-traversal guard; override for tests).
    runs_root = Path(os.environ.get("ANGEL_RUNS_ROOT", str(Path.home() / ".angel" / "runs"))).resolve()
    resolved = run_dir.resolve()
    if resolved != runs_root and runs_root not in resolved.parents:
        sys.exit(f"refusing to write outside runs root {runs_root}: {run_dir}")

    p = run_dir / "dispositions.json"
    if p.is_file():
        # Idempotent no-op: recorded dispositions (or a prior skeleton) win.
        print(f"dispositions.json already exists, left untouched: {p}")
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

    data = {}
    if (run_dir / "EXPERIMENT").is_file():
        data["experiment"] = True

    count = 0
    for f in findings:
        fid = f.get("id") if isinstance(f, dict) else None
        if not fid:
            print(f"warning: finding without id skipped: {f!r}", file=sys.stderr)
            continue
        if fid == "experiment":  # would collide with the marker key
            print("warning: finding id 'experiment' collides with marker key, skipped", file=sys.stderr)
            continue
        if not FINDING_ID_RE.match(fid):
            print(f"warning: finding id {fid!r} fails charset check "
                  f"(must match ^[a-zA-Z0-9_-]{{1,64}}$), invalid — skipped", file=sys.stderr)
            continue
        # record-disposition.py's entry schema; recorded_at stays null until a
        # real disposition lands ("no-record" was never recorded by anyone).
        data[fid] = {"disposition": "no-record", "note": "", "recorded_at": None}
        count += 1

    p.write_text(json.dumps(data, indent=2) + "\n")
    tag = " (experiment)" if data.get("experiment") is True else ""
    print(f"skeleton written: {count} findings -> no-record in {p}{tag}")


if __name__ == "__main__":
    main()
