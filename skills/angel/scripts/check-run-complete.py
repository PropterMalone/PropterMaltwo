#!/usr/bin/env python3
# pattern: imperative shell
"""Verify a NineAngel run dir persisted its artifacts — the rigor floor.

A run is "complete" when it wrote all of: findings-snapshot.json, usage.json,
a non-empty findings/ dir, and a matching run: line in usage.log. Most history
failed this silently (only 4/30 runs were minable). This makes the gap
checkable: run it after a /angel run (exits nonzero if incomplete), or with
--all to audit the whole run history.

Usage: check-run-complete.py <run_dir>        # single run, exit 0/1
       check-run-complete.py --all            # audit every run dir
"""
import argparse
import os
import sys
from pathlib import Path


def usage_log_path():
    env = os.environ.get("ANGEL_USAGE_LOG")  # override for tests
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "usage.log"


def log_has_run(run_dir):
    lp = usage_log_path()
    if not lp.is_file():
        return False
    needle = f"run:{run_dir}"
    try:
        for line in lp.read_text().splitlines():
            i = line.find(needle)
            if i >= 0:
                after = line[i + len(needle):]
                if after == "" or after[0] == " ":  # boundary: avoid prefix collision
                    return True
        return False
    except Exception:
        return False


def check(run_dir):
    missing = []
    if not (run_dir / "findings-snapshot.json").is_file():
        missing.append("findings-snapshot.json")
    if not (run_dir / "usage.json").is_file():
        missing.append("usage.json")
    fdir = run_dir / "findings"
    if not (fdir.is_dir() and any(fdir.glob("*.md"))):
        missing.append("findings/*.md")
    if not log_has_run(run_dir):
        missing.append("usage.log run: line")
    return missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--runs-dir", default=str(Path.home() / ".angel" / "runs"))
    args = ap.parse_args()

    if args.all:
        runs_dir = Path(args.runs_dir)
        if not runs_dir.is_dir():
            sys.exit(f"no runs dir: {runs_dir}")
        runs = sorted(d for d in runs_dir.iterdir() if d.is_dir())
        complete = 0
        for d in runs:
            miss = check(d)
            if miss:
                print(f"INCOMPLETE  {d.name}  missing: {', '.join(miss)}")
            else:
                complete += 1
                print(f"OK          {d.name}")
        print(f"\n{complete}/{len(runs)} runs complete")
        sys.exit(0 if complete == len(runs) else 1)  # nonzero if any incomplete (for `--all || alert`)

    if not args.run_dir:
        sys.exit("usage: check-run-complete.py <run_dir> | --all")
    rd = Path(args.run_dir)
    if not rd.is_dir():
        sys.exit(f"run dir not found: {rd}")
    miss = check(rd)
    if miss:
        print(f"INCOMPLETE: {rd}\n  missing: {', '.join(miss)}", file=sys.stderr)
        sys.exit(1)
    print(f"OK: {rd} complete")


if __name__ == "__main__":
    main()
