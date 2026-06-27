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
import json
import os
import re
import sys
from pathlib import Path

RUN_RE = re.compile(r"run:(\S+)")
BALL_RE = re.compile(r"_ball(\d+)\.md$")


def multiball_n(run_dir, snap):
    """Infer the pass count N for a multiball run, else None.

    Prefer the snapshot's `multiball` field (an int N); fall back to counting
    the `<persona>_ball<i>.md` passes on disk. JSON `false`/absent → single-pass."""
    if isinstance(snap, dict):
        mb = snap.get("multiball")
        if not isinstance(mb, bool) and isinstance(mb, int) and mb >= 2:
            return mb
    fdir = run_dir / "findings"
    if fdir.is_dir():
        idx = [int(m.group(1)) for f in fdir.glob("*_ball*.md")
               if (m := BALL_RE.search(f.name))]
        if idx and max(idx) >= 2:
            return max(idx)
    return None


def within_persona_runs_ok(snap):
    """True if a multiball snapshot persisted a well-formed `within_persona_runs`.

    Schema v2 (integrator.md): a non-empty dict, each value a list of per-pass
    finding sub-arrays, with at least one persona recording >= 2 passes. The
    2026-06-19 N=5 run failed this — the field was absent entirely while 30 ball
    files sat on disk, so subsample-analyzer.py read zero. This makes the
    integrator's emission a mechanical gate, not a disciplined hope."""
    if not isinstance(snap, dict):
        return False
    wpr = snap.get("within_persona_runs")
    if not isinstance(wpr, dict) or not wpr:
        return False
    # Each persona maps to a list of per-pass sub-arrays, and each pass must
    # itself be a list of findings — NOT a prose string. The 2026-06-19 failure
    # shape was prose `consensus` strings; reject anything that isn't the
    # structured per-pass record so a stringly-typed record can't masquerade as
    # one. (Empty sub-arrays like [[],[]] ARE valid — an all-clean multiball
    # run that genuinely found nothing in either pass.)
    for passes in wpr.values():
        if not isinstance(passes, list):
            return False
        if not all(isinstance(p, list) for p in passes):
            return False
    # At least one persona must record >=2 passes (proof multiball ran). We
    # don't require ALL personas to be >=2: single-persona multiball leaves the
    # others at 1 pass, and the per-persona N isn't carried here.
    return any(len(passes) >= 2 for passes in wpr.values())


def usage_log_path():
    env = os.environ.get("ANGEL_USAGE_LOG")  # override for tests
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "usage.log"


def logged_run_dirs():
    """Parse usage.log ONCE into the set of run-dir strings it mentions.

    The \\S+ capture reproduces the old per-needle boundary check (the run dir
    is the whole space-delimited token), and turns the --all audit from
    O(runs x log-lines) re-reads into one read + set lookups."""
    lp = usage_log_path()
    if not lp.is_file():
        return set()
    try:
        return {m.group(1) for m in RUN_RE.finditer(lp.read_text())}
    except Exception:
        return set()


def check(run_dir, logged):
    missing = []
    if not (run_dir / "findings-snapshot.json").is_file():
        missing.append("findings-snapshot.json")
    if not (run_dir / "usage.json").is_file():
        missing.append("usage.json")
    fdir = run_dir / "findings"
    if not (fdir.is_dir() and any(fdir.glob("*.md"))):
        missing.append("findings/*.md")
    if str(run_dir) not in logged:
        missing.append("usage.log run: line")
    # Multiball runs must persist the per-pass record — without it the run is
    # unmeasurable (subsample-analyzer/backstop read `within_persona_runs`).
    snap_path = run_dir / "findings-snapshot.json"
    if snap_path.is_file():
        try:
            snap = json.loads(snap_path.read_text())
        except Exception:
            snap = None
        n = multiball_n(run_dir, snap)
        if n and not within_persona_runs_ok(snap):
            missing.append(f"within_persona_runs (multiball N={n})")
    return missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--runs-dir", default=str(Path.home() / ".angel" / "runs"))
    args = ap.parse_args()

    logged = logged_run_dirs()

    if args.all:
        runs_dir = Path(args.runs_dir)
        if not runs_dir.is_dir():
            sys.exit(f"no runs dir: {runs_dir}")
        runs = sorted(d for d in runs_dir.iterdir() if d.is_dir())
        complete = 0
        for d in runs:
            miss = check(d, logged)
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
    miss = check(rd, logged)
    if miss:
        print(f"INCOMPLETE: {rd}\n  missing: {', '.join(miss)}", file=sys.stderr)
        sys.exit(1)
    print(f"OK: {rd} complete")


if __name__ == "__main__":
    main()
