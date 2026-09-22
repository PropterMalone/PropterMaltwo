#!/usr/bin/env python3
# pattern: imperative shell
"""Verify a NineAngel run dir persisted its artifacts — the rigor floor.

A run is "complete" when it wrote all required snapshot, usage, findings, and
index artifacts. This makes incomplete records visible: run it after a review
(exits nonzero if incomplete), or use `--all` to audit the run directory.

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

    Priority: (1) snapshot's `multiball` int field; (2) MULTIBALL marker file
    (written by the orchestrator at run start, per SKILL.md §3.4); (3) passes/
    dir (written by Stage-1 reconcilers, per ADR-11); (4) legacy _ball*.md
    files in findings/ (back-compat). JSON `false`/absent → single-pass."""
    if isinstance(snap, dict):
        mb = snap.get("multiball")
        if not isinstance(mb, bool) and isinstance(mb, int) and mb >= 2:
            return mb
    # MULTIBALL marker (new canonical signal — one-line integer file)
    marker = run_dir / "MULTIBALL"
    if marker.is_file():
        try:
            n = int(marker.read_text().strip())
            if n >= 2:
                return n
        except (ValueError, OSError):
            pass
    # passes/ dir (ADR-11 stage-1 artifacts)
    pdir = run_dir / "passes"
    if pdir.is_dir() and any(pdir.glob("*.md")):
        # count distinct pass indices from filenames like {persona}-p{i}.md
        import re as _re
        pidx = set()
        for f in pdir.glob("*-p*.md"):
            m = _re.search(r"-p(\d+)\.md$", f.name)
            if m:
                pidx.add(int(m.group(1)))
        if len(pidx) >= 2 or (pidx and max(pidx) >= 2):
            return max(pidx) if pidx else 2
    # legacy _ball*.md files (back-compat)
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
    finding sub-arrays, with at least one persona recording >= 2 passes. This
    makes the integrator's emission a mechanical gate, not a disciplined hope."""
    if not isinstance(snap, dict):
        return False
    wpr = snap.get("within_persona_runs")
    if not isinstance(wpr, dict) or not wpr:
        return False
    # Each persona maps to a list of per-pass sub-arrays, each pass a list of
    # finding OBJECTS — not prose strings or reconciled id-ref strings. This
    # element-level check is version-independent (ADR-12) and rejects malformed
    # legacy shapes. (Empty sub-arrays like [[],[]] ARE valid — an all-clean
    # multiball run that genuinely found nothing.)
    for passes in wpr.values():
        if not isinstance(passes, list):
            return False
        for p in passes:
            if not isinstance(p, list) or not all(isinstance(f, dict) for f in p):
                return False
    # At least one persona must record >=2 passes (proof multiball ran). We
    # don't require ALL personas to be >=2: single-persona multiball leaves the
    # others at 1 pass, and the per-persona N isn't carried here.
    return any(len(passes) >= 2 for passes in wpr.values())


_PASS_IDX_RE = re.compile(r"[-_](?:p|pass)(\d+)\.md$", re.IGNORECASE)


def provenance_check(run_dir):
    """ADR-12 provenance gate: does the stored within_persona_runs equal a fresh
    recompute from passes/*.md? Delegates to assemble-wpr. A parse/import failure is
    a distinct `provenance-uncomputable` result (never aborts finalize — the review's
    'a parser bug silently drops a valid run' finding). Returns (ok, reason)."""
    try:
        import importlib.util
        p = Path(__file__).resolve().parent / "assemble-wpr.py"
        spec = importlib.util.spec_from_file_location("assemble_wpr", p)
        aw = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(aw)
        return aw.check(str(run_dir))
    except Exception as e:  # noqa: BLE001 — a broken parser must not crash the gate
        return False, f"provenance-uncomputable: {e.__class__.__name__}: {e}"


def incomplete_passes(run_dir, snap, n):
    """For each persona in within_persona_runs, list pass indices 1..N missing from
    passes/ on disk (a missed --pass call). A --failed stub counts as present. Catches
    the gap the provenance check can't (both stored + recompute see the same missing
    pass, so they'd still match)."""
    pdir = run_dir / "passes"
    if not pdir.is_dir():
        return ""
    wpr = (snap or {}).get("within_persona_runs") or {}
    bad = []
    for persona in wpr:
        present = set()
        for f in pdir.glob(f"{persona}[-_]p*.md"):
            m = _PASS_IDX_RE.search(f.name)
            if m:
                present.add(int(m.group(1)))
        for f in pdir.glob(f"{persona}[-_]pass*.md"):
            m = _PASS_IDX_RE.search(f.name)
            if m:
                present.add(int(m.group(1)))
        missing_idx = [i for i in range(1, n + 1) if i not in present]
        if missing_idx:
            bad.append(f"{persona}:{missing_idx}")
    return ", ".join(bad)


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


def check(run_dir, logged, pre_append=False):
    """pre_append=True skips the usage.log requirement.

    ADR-12 moved append-usage-log AFTER this gate so a gate failure stops the line
    instead of duplicating it. That makes the usage.log check circular when this runs
    as finalize-run.sh's pre-append gate: the line it demands is only written once the
    gate passes, so a first finalize could never succeed. The edit map didn't catch
    this — the check made sense only while the append ran first.

    So the artifact is still required for an `--all` audit (there, a run genuinely
    should be in the index), and skipped when we're the thing deciding whether to
    write it.
    """
    missing = []
    if not (run_dir / "findings-snapshot.json").is_file():
        missing.append("findings-snapshot.json")
    if not (run_dir / "usage.json").is_file():
        missing.append("usage.json")
    fdir = run_dir / "findings"
    if not (fdir.is_dir() and any(fdir.glob("*.md"))):
        missing.append("findings/*.md")
    if not pre_append and str(run_dir) not in logged:
        missing.append("usage.log run: line")
    # Multiball runs must persist the per-pass record — without it the run is
    # unmeasurable (subsample-analyzer/backstop read `within_persona_runs`).
    snap_path = run_dir / "findings-snapshot.json"
    if snap_path.is_file():
        try:
            snap = json.loads(snap_path.read_text())
        except Exception:
            snap = None
        reducer_meta = None
        meta_path = run_dir / "run-meta.json"
        if meta_path.is_file():
            try:
                reducer_meta = json.loads(meta_path.read_text())
            except Exception:
                reducer_meta = {}
        reducer_era = ((snap or {}).get("version") == 3 or
                       (reducer_meta or {}).get("integration_pipeline") == "semantic-reducer-v1")
        if reducer_era:
            if not (run_dir / "report.md").is_file():
                missing.append("report.md")
            if (reducer_meta or {}).get("status") != "ready":
                missing.append("ready run-meta.json")
            for name in ("integration-workset.json", "integration-decisions.json"):
                if not (run_dir / name).is_file():
                    missing.append(name)
            if (snap or {}).get("version") != 3 or (snap or {}).get("decision_schema_version") != 1:
                missing.append("valid reducer-era snapshot v3")
        n = multiball_n(run_dir, snap)
        if n:
            if not within_persona_runs_ok(snap):
                missing.append(f"within_persona_runs (multiball N={n})")
            else:
                # Mechanical-capture (v3) runs have passes/ on disk -> provenance +
                # pass-completeness. Legacy LLM-assembled runs (no passes/) get only the
                # structural check above (version-independent, per ADR-12 back-compat).
                pdir = run_dir / "passes"
                if pdir.is_dir() and any(pdir.glob("*p*.md")):
                    ok, reason = provenance_check(run_dir)
                    if not ok:
                        missing.append(f"within_persona_runs provenance ({reason})")
                    gap = incomplete_passes(run_dir, snap, n)
                    if gap:
                        missing.append(f"passes incomplete (N={n}: {gap})")
    return missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--runs-dir", default=str(Path.home() / ".angel" / "runs"))
    ap.add_argument("--pre-append", action="store_true",
                    help="skip the usage.log requirement; for finalize-run.sh's pre-append gate (ADR-12)")
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
    miss = check(rd, logged, pre_append=args.pre_append)
    if miss:
        print(f"INCOMPLETE: {rd}\n  missing: {', '.join(miss)}", file=sys.stderr)
        sys.exit(1)
    print(f"OK: {rd} complete")


if __name__ == "__main__":
    main()
