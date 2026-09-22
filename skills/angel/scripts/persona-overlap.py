#!/usr/bin/env python3
# pattern: imperative shell (I/O + reporting); pure overlap math in the FUNCTIONAL CORE block
"""Cross-persona overlap analyzer — the merge/remove lever for the 9A roster.

THE QUESTION: when two personas repeatedly surface the same issues, can they be
merged without losing coverage? Single-pass solo-catch counts are confounded by
sampling variance, so this analyzer estimates each persona's pool as the
matcher-deduped union of its N multiball passes, then measures pool overlap.

METRICS (per snapshot, then aggregated across snapshots, persona-canonicalized):
  - pool(persona)      = matcher-dedup union of the persona's N passes.
  - overlap(A->B)      = fraction of pool(A) findings that also appear in pool(B).
                         Directed: overlap(A->B) != overlap(B->A) when |pools| differ.
  - unique_rate(A)     = fraction of pool(A) matched by NO other persona in the
                         same snapshot -> the REMOVAL signal (low = dominated by
                         the field). corroboration_rate = 1 - unique_rate.
  - merge candidate    = a pair with high overlap in BOTH directions (same lens).

SAMPLING CAVEAT (direction matters). Each observed pool may be incomplete, so a
finding in B's true pool that B did not sample will not match: measured overlap
understates true overlap and unique_rate overstates true uniqueness. A low
measured unique_rate is therefore stronger evidence than a high one; the bias is
conservative for a "don't lose coverage" goal.

NULL-FILE CAVEAT. The shared matcher keys on file+title; absence findings carry
file=null and never match cross-persona under the strict matcher, so they always
read as "unique." Absence-heavy personas (blindspot, thousand, heir) are thus
systematically flagged unique here. Within a persona's own passes we dedup
null-file findings by title alone (same author, same run — safe). Cross-persona,
title-only matching of null-file findings is gated behind --title-fallback
(different authors title differently — riskier); without it, null-file findings
are counted and REPORTED as unmatchable rather than silently inflating unique.

Usage:
  persona-overlap.py [snapshot.json ...]              # explicit files (fixtures/tests)
  persona-overlap.py [--runs-dir ~/.angel/runs]       # scan for multiball snapshots
  persona-overlap.py [--threshold 0.5] [--severity importantplus|all]
                     [--title-fallback] [--min-cooccur 3] [--json]
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # runs as __main__ from any CWD
from finding_match import (
    SEV_RANK, file_match, finding_match, normalize_finding, title_overlap,
    wpr_is_analyzable, persona_passes_analyzable,
)
from persona_aliases import build_persona_aliases, canon_persona


# ============================ FUNCTIONAL CORE ============================
# Pure: no I/O. Overlap math, unit-testable in isolation.

def issue_match(fa, fb, threshold, title_fallback, mode="file-title", line_window=10):
    """Do two normalized findings describe the same issue?

    mode controls the both-have-file case — a bracket for cross-persona overlap
    (which no single instrument resolves):
      - "file-title" (default): same file + title-token overlap >= threshold.
        UNDER-counts (different mandates title the same bug differently) -> LOWER bound.
      - "file": same file/basename, title ignored. OVER-counts (many personas flag
        one file for different reasons) -> UPPER bound.
      - "file-line": same file AND (line within +-line_window OR title overlap
        >= threshold). A principled INTERIOR point: line proximity catches
        same-location findings with disjoint titles; the title branch preserves
        file-title matches AND covers the ~half of findings that carry no line.
        Strictly file-title <= file-line <= file.
    When at least one finding lacks a file (absence findings, file=null), fall
    back to title-token overlap only IF title_fallback is set — else no match
    (strict default). dedup_pool always uses file-title, so mode only ever loosens
    CROSS-persona matching, never within-persona dedup."""
    if fa["nfile"] and fb["nfile"]:
        if not file_match(fa["nfile"], fb["nfile"]):
            return False
        if mode == "file":
            return True
        if mode == "file-line":
            la, lb = fa.get("line"), fb.get("line")
            if la is not None and lb is not None and abs(la - lb) <= line_window:
                return True
            return title_overlap(fa["toks"], fb["toks"]) >= threshold
        return title_overlap(fa["toks"], fb["toks"]) >= threshold  # file-title
    if not title_fallback:
        return False
    return title_overlap(fa["toks"], fb["toks"]) >= threshold


def dedup_pool(findings, threshold):
    """Greedy single-linkage dedup of ONE persona's findings across its passes.

    Returns the representative normalized findings (one per distinct issue).
    Uses title_fallback=True: within a single persona's own passes, a repeated
    null-file absence finding is the same issue and should collapse."""
    reps = []
    for f in findings:
        if not any(issue_match(f, r, threshold, True) for r in reps):
            reps.append(f)
    return reps


def snapshot_overlap(pools, threshold, title_fallback, mode="file-title", line_window=10):
    """One snapshot's overlap structure. pools: {persona: [normalized findings]}.

    Returns per-persona sizes/unique/nullfile counts and per-ordered-pair matched
    counts. Pure — the shell accumulates these across snapshots.
      sizes[A]           = |pool(A)|
      unique[A]          = # findings in pool(A) matched by no other persona
      nullfile[A]        = # findings in pool(A) with no file coordinate
      matched[(A,B)]     = # findings in pool(A) that match >=1 finding in pool(B)
    """
    personas = list(pools)
    sizes = {p: len(pools[p]) for p in personas}
    nullfile = {p: sum(1 for f in pools[p] if not f["nfile"]) for p in personas}
    unique = {p: 0 for p in personas}
    matched = defaultdict(int)  # (A, B) -> count of A's findings matched in B
    for a in personas:
        for f in pools[a]:
            found_any = False
            for b in personas:
                if b == a:
                    continue
                if any(issue_match(f, g, threshold, title_fallback, mode, line_window) for g in pools[b]):
                    matched[(a, b)] += 1
                    found_any = True
            if not found_any:
                unique[a] += 1
    return {"sizes": sizes, "unique": unique, "nullfile": nullfile, "matched": dict(matched)}


# ============================ IMPERATIVE SHELL ============================

def load_snapshots(files, runs_dir):
    """Return (snapshots, skipped). snapshots: [(label, wpr)] with the analyzable
    structured per-pass shape; skipped: [(label, reason)] for malformed legacy
    shapes. Same skip-and-report contract as subsample-analyzer, so one bad
    snapshot cannot crash the scan."""
    paths = list(files)
    if not paths and runs_dir:
        rd = Path(runs_dir).expanduser()
        if rd.is_dir():
            paths = sorted(rd.glob("*/findings-snapshot.json"))
    snaps, skipped = [], []
    for p in paths:
        p = Path(p)
        try:
            data = json.loads(p.read_text())
        except Exception:
            continue
        wpr = data.get("within_persona_runs")
        if not wpr:
            continue
        label = p.parent.name if p.name == "findings-snapshot.json" else p.name
        if not wpr_is_analyzable(wpr):
            skipped.append((label, "unanalyzable within_persona_runs shape (id-ref/prose)"))
            continue
        snaps.append((label, wpr))
    return snaps, skipped


def build_pools(wpr, threshold, severity, amap):
    """One snapshot's within_persona_runs -> {canon_persona: deduped pool}.

    Canonicalizes persona keys (merging e.g. hyper/hypercritical) and, if two raw
    keys canonicalize together in one snapshot, unions their passes first."""
    raw = defaultdict(list)  # canon persona -> flat list of normalized findings
    for persona, passes in wpr.items():
        if not persona_passes_analyzable(passes) or len(passes) < 2:
            continue  # need >=2 passes to call the union a pool estimate
        cp = canon_persona(persona, amap)
        for pf in passes:
            for f in pf:
                nf = normalize_finding(f)
                if severity == "importantplus" and SEV_RANK[nf["sev"]] < 2:
                    continue
                raw[cp].append(nf)
    return {p: dedup_pool(fs, threshold) for p, fs in raw.items() if fs}


def analyze(snapshots, threshold, severity, title_fallback, amap, mode="file-title", line_window=10):
    """Aggregate overlap across snapshots. Returns (per_persona, pairs, coverage)."""
    pool_size = defaultdict(int)
    uniq = defaultdict(int)
    nullf = defaultdict(int)
    snaps_present = defaultdict(int)
    pair_matched = defaultdict(int)   # (A,B) -> matched count summed over snapshots both present
    pair_denom = defaultdict(int)     # (A,B) -> |pool(A)| summed over snapshots both present
    pair_cooccur = defaultdict(int)   # (A,B) unordered co-occurrence count
    total_pool_findings = 0

    for _label, wpr in snapshots:
        pools = build_pools(wpr, threshold, severity, amap)
        if len(pools) < 1:
            continue
        so = snapshot_overlap(pools, threshold, title_fallback, mode, line_window)
        present = list(pools)
        for p in present:
            pool_size[p] += so["sizes"][p]
            uniq[p] += so["unique"][p]
            nullf[p] += so["nullfile"][p]
            snaps_present[p] += 1
            total_pool_findings += so["sizes"][p]
        for a in present:
            for b in present:
                if a == b:
                    continue
                pair_denom[(a, b)] += so["sizes"][a]
                pair_matched[(a, b)] += so["matched"].get((a, b), 0)
        for i, a in enumerate(present):
            for b in present[i + 1:]:
                pair_cooccur[frozenset((a, b))] += 1

    per_persona = {}
    for p in pool_size:
        n = pool_size[p]
        per_persona[p] = {
            "pool_findings": n,
            "unique": uniq[p],
            "unique_rate": (uniq[p] / n) if n else None,
            "corroboration_rate": (1 - uniq[p] / n) if n else None,
            "nullfile": nullf[p],
            "nullfile_frac": (nullf[p] / n) if n else None,
            "snapshots": snaps_present[p],
        }

    # Directed overlaps, then symmetric merge score = min(A->B, B->A).
    overlap = {}
    for (a, b), den in pair_denom.items():
        overlap[(a, b)] = (pair_matched[(a, b)] / den) if den else None
    pairs = []
    for key, cooccur in pair_cooccur.items():
        a, b = sorted(key)
        ab, ba = overlap.get((a, b)), overlap.get((b, a))
        if ab is None or ba is None:
            continue
        pairs.append({
            "a": a, "b": b, "cooccur": cooccur,
            "overlap_a_to_b": ab, "overlap_b_to_a": ba,
            "merge_score": min(ab, ba), "max_overlap": max(ab, ba),
        })
    pairs.sort(key=lambda d: d["merge_score"], reverse=True)

    coverage = {
        "snapshots_analyzed": sum(1 for _l, w in snapshots if build_pools(w, threshold, severity, amap)),
        "personas": len(per_persona),
        "total_pool_findings": total_pool_findings,
    }
    return per_persona, pairs, coverage


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshots", nargs="*", help="explicit findings-snapshot.json paths")
    ap.add_argument("--runs-dir", default=str(Path.home() / ".angel" / "runs"))
    ap.add_argument("--threshold", type=float, default=0.5, help="title overlap-coefficient to call a match")
    ap.add_argument("--severity", choices=["importantplus", "all"], default="importantplus")
    ap.add_argument("--match", choices=["file-title", "file-line", "file"], default="file-title",
                    help="cross-persona match rule: file-title (strict, lower bound) | "
                         "file-line (same file + near-line-OR-title, principled interior) | "
                         "file (title-agnostic, upper bound). Brackets true overlap.")
    ap.add_argument("--line-window", type=int, default=10,
                    help="line-proximity window for --match file-line (default +-10)")
    ap.add_argument("--title-fallback", action="store_true",
                    help="match null-file absence findings cross-persona by title tokens only (weaker)")
    ap.add_argument("--min-cooccur", type=int, default=3,
                    help="min snapshots two personas must co-occur in to list as a merge candidate")
    ap.add_argument("--skill-dir", default=None, help="persona alias map root (default: parent of this script)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    skill_dir = Path(args.skill_dir).resolve() if args.skill_dir else Path(__file__).resolve().parent.parent
    amap = build_persona_aliases(skill_dir)

    snaps, skipped = load_snapshots(args.snapshots, None if args.snapshots else args.runs_dir)
    per_persona, pairs, coverage = analyze(
        snaps, args.threshold, args.severity, args.title_fallback, amap, args.match, args.line_window)

    if args.json:
        print(json.dumps({
            "params": {"threshold": args.threshold, "severity": args.severity,
                       "match": args.match, "line_window": args.line_window,
                       "title_fallback": args.title_fallback, "min_cooccur": args.min_cooccur},
            "coverage": {**coverage, "skipped_snapshots": len(skipped)},
            "skipped": [{"label": lbl, "reason": r} for lbl, r in skipped],
            "per_persona": per_persona,
            "pairs": pairs,
        }, indent=2))
        return

    L = ["# NineAngel cross-persona overlap analysis", ""]
    _mode_note = {"file-title": "strict — lower bound",
                  "file-line": f"same file + near-line(±{args.line_window})-or-title — interior",
                  "file": "title-agnostic — upper bound"}[args.match]
    L.append(f"Params: match **{args.match}** ({_mode_note}), "
             f"threshold **{args.threshold}**, severity **{args.severity}**, "
             f"title-fallback **{'on' if args.title_fallback else 'off'}**.")
    L.append(f"Coverage: **{coverage['snapshots_analyzed']}** multiball snapshot(s), "
             f"**{coverage['personas']}** canonical personas, "
             f"**{coverage['total_pool_findings']}** pooled findings.")
    if skipped:
        L.append(f"Skipped **{len(skipped)}** unanalyzable snapshot(s) (id-ref/prose shape).")
    L.append("")
    if not per_persona:
        L.append("_No analyzable multiball data._")
        print("\n".join(L))
        return

    L.append("## Removal signal — per-persona unique rate (low = dominated by the field)")
    L.append("")
    L.append("`unique` = fraction of a persona's pool that NO other persona found. "
             "Sampling makes this an UPPER bound (true uniqueness is lower), so a low value is a "
             "confident remove/merge signal; a high value is uncertain. `null%` = share of pool with "
             "no file coordinate (unmatchable cross-persona unless --title-fallback) — inflates unique.")
    L.append("")
    L.append("| persona | unique | corroborated | pool | snaps | null% |")
    L.append("|---|--:|--:|--:|--:|--:|")
    for p, d in sorted(per_persona.items(), key=lambda kv: (kv[1]["unique_rate"] if kv[1]["unique_rate"] is not None else 1)):
        ur = f"{100*d['unique_rate']:.0f}%" if d["unique_rate"] is not None else "—"
        cr = f"{100*d['corroboration_rate']:.0f}%" if d["corroboration_rate"] is not None else "—"
        nf = f"{100*d['nullfile_frac']:.0f}%" if d["nullfile_frac"] is not None else "—"
        L.append(f"| {p} | {ur} | {cr} | {d['pool_findings']} | {d['snapshots']} | {nf} |")
    L.append("")

    L.append("## Merge candidates — pairs finding the same issues in both directions")
    L.append("")
    L.append(f"`merge_score` = min(overlap A→B, overlap B→A). High in BOTH directions = same lens. "
             f"Listed: co-occurrence ≥ {args.min_cooccur}, merge_score ≥ 25%, top 20.")
    L.append("")
    L.append("| A | B | A→B | B→A | merge_score | co-occ |")
    L.append("|---|---|--:|--:|--:|--:|")
    shown = 0
    for pr in pairs:
        if pr["cooccur"] < args.min_cooccur or pr["merge_score"] < 0.25:
            continue
        L.append(f"| {pr['a']} | {pr['b']} | {100*pr['overlap_a_to_b']:.0f}% | "
                 f"{100*pr['overlap_b_to_a']:.0f}% | {100*pr['merge_score']:.0f}% | {pr['cooccur']} |")
        shown += 1
        if shown >= 20:
            break
    if shown == 0:
        L.append("| _(none above thresholds)_ | | | | | |")
    L.append("")
    L.append("_Caveats: overlaps UNDER-state true pool overlap (each pool is ~64-72% complete at N=2-3), "
             "so real redundancy is higher than shown. Model-mixed across personas/eras — not yet split "
             "per (persona, model). Null-file absence findings are unmatchable under the strict matcher._")
    print("\n".join(L))


if __name__ == "__main__":
    main()
