#!/usr/bin/env python3
# pattern: imperative shell (I/O + reporting); pure analysis in the FUNCTIONAL CORE block
"""Subsample-N analyzer — tune multiball's N from real per-pass data.

THE QUESTION (ADR-03 reboot condition 1, backlog "Subsample-N analyzer"):
multiball runs each persona N independent times because a single pass samples
only ~40% of a persona's Important+ findings (recurrence-pilot.py). But what is
the right N? Each extra pass costs another full output generation (uncacheable),
so we want the SMALLEST N that still recovers most of what the persona can find.

This reads the `within_persona_runs` field a multiball run writes into its
findings-snapshot.json (schema v2: `{persona: [[pass-1 findings], [pass-2 ...]]}`)
and computes, per persona and aggregated:

  - RECALL-VS-N CURVE. Treat the union (matcher-deduped) of all N passes as the
    persona's "full" finding set. For each k=1..N, recall(k) = expected fraction
    of that full set recovered by a random k-of-N subset (mean over all C(N,k)
    subsets, union+dedup within the subset). recall(1) is the single-pass recall
    (~the 40% number); recall(N)=1.0 by construction. Where the curve flattens is
    where extra passes stop paying — that's the N to pick.

  - PER-PERSONA REPRODUCIBILITY = recall(1): the mean fraction of passes a finding
    appears in. Low = stochastic persona (extra passes help a lot); high = stable
    (N can be small). Cleaner than recurrence-pilot's cross-run replicate pairs —
    this is same-code, same-run, no metadata join.

Reuses the finding matcher from finding_match.py (same definition the cross-run
pilot uses). No real multiball data exists yet (the 2026-06-07 default-ON window
was aborted before producing any), so this is validated on synthetic fixtures;
it harvests real curves once default-ON multiball runs accrue.

Usage:
  subsample-analyzer.py [snapshot.json ...]      # explicit files (fixtures/tests)
  subsample-analyzer.py [--runs-dir ~/.angel/runs]   # scan for multiball snapshots
  subsample-analyzer.py [--threshold 0.5] [--severity importantplus|all] [--json]
"""
import argparse
import json
import sys
from collections import defaultdict
from itertools import combinations
from math import comb
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # runs as __main__ from any CWD
from finding_match import SEV_RANK, finding_match, normalize_finding


# ============================ FUNCTIONAL CORE ============================
# Pure: no I/O. Clustering + recall math, unit-testable in isolation.

def cluster_pass_sets(passes, threshold):
    """passes: list (per pass) of lists of matcher-ready finding dicts.

    Greedy single-linkage clustering across all passes by the shared matcher:
    each cluster is the set of pass indices that contributed >=1 matching finding.
    A pass contributes to a cluster at most once (set semantics), so duplicate
    findings within one pass don't inflate presence. Returns a list of
    frozenset(pass_index) — one per distinct issue ("the full finding set").
    """
    reps = []          # cluster representative findings (first seen)
    pass_sets = []     # cluster -> set of pass indices
    for i, pf in enumerate(passes):
        for f in pf:
            hit = None
            for ci, rep in enumerate(reps):
                if finding_match(f, rep, threshold):
                    hit = ci
                    break
            if hit is None:
                reps.append(f)
                pass_sets.append({i})
            else:
                pass_sets[hit].add(i)
    return [frozenset(s) for s in pass_sets]


def recall_at_k(cluster_sets, n, k):
    """Mean over all C(n,k) pass-subsets of (clusters touched by subset / total).

    A cluster is 'touched' by subset S if any of its pass indices is in S. With
    no clusters, recall is undefined (None)."""
    total = len(cluster_sets)
    if total == 0 or k < 1 or k > n:
        return None
    if k == n:
        return 1.0
    n_subsets = comb(n, k)
    acc = 0
    for subset in combinations(range(n), k):
        s = set(subset)
        acc += sum(1 for c in cluster_sets if c & s)
    return acc / (n_subsets * total)


def recall_curve(cluster_sets, n):
    """{k: recall(k)} for k=1..n. recall(n) == 1.0 by construction."""
    return {k: recall_at_k(cluster_sets, n, k) for k in range(1, n + 1)}


def reproducibility(cluster_sets, n):
    """Mean fraction of passes a finding appears in (== recall(1)). None if empty."""
    if not cluster_sets:
        return None
    return sum(len(c) for c in cluster_sets) / (len(cluster_sets) * n)


def passes_for_severity(raw_passes, severity):
    """Normalize each pass's raw findings; filter to Important+ if requested."""
    out = []
    for pf in raw_passes:
        norm = [normalize_finding(f) for f in (pf or [])]
        if severity == "importantplus":
            norm = [f for f in norm if SEV_RANK[f["sev"]] >= 2]
        out.append(norm)
    return out


# ============================ IMPERATIVE SHELL ============================

def iter_snapshots(files, runs_dir):
    """Yield (label, within_persona_runs dict) for snapshots that have one."""
    paths = list(files)
    if not paths and runs_dir:
        rd = Path(runs_dir).expanduser()
        if rd.is_dir():
            paths = sorted(rd.glob("*/findings-snapshot.json"))
    for p in paths:
        p = Path(p)
        try:
            data = json.loads(p.read_text())
        except Exception:
            continue
        wpr = data.get("within_persona_runs")
        if not wpr:  # null or empty -> not a multiball run
            continue
        label = p.parent.name if p.name == "findings-snapshot.json" else p.name
        yield label, wpr


def analyze(snapshots, threshold, severity):
    """Per (persona, N) instance: cluster passes, compute curve + reproducibility.

    Aggregates recall(k) across instances grouped by N (you can only average a
    k-point across runs that ran at least k passes)."""
    instances = []  # {label, persona, n, clusters, full, curve, repro}
    for label, wpr in snapshots:
        for persona, raw_passes in wpr.items():
            n = len(raw_passes)
            if n < 2:
                continue
            passes = passes_for_severity(raw_passes, severity)
            clusters = cluster_pass_sets(passes, threshold)
            if not clusters:
                continue
            instances.append({
                "label": label, "persona": persona, "n": n,
                "full": len(clusters),
                "curve": recall_curve(clusters, n),
                "repro": reproducibility(clusters, n),
            })

    # Recall-vs-N aggregated by N (weight each instance by its full-set size).
    by_n = defaultdict(list)
    for inst in instances:
        by_n[inst["n"]].append(inst)
    agg_curves = {}
    for n, insts in by_n.items():
        pts = {}
        for k in range(1, n + 1):
            num = sum(inst["curve"][k] * inst["full"] for inst in insts)
            den = sum(inst["full"] for inst in insts)
            pts[k] = (num / den) if den else None
        agg_curves[n] = {"instances": len(insts), "findings": den, "recall": pts}

    # Per-persona reproducibility (weight by full-set size across its instances).
    per_persona = {}
    pp = defaultdict(lambda: {"num": 0.0, "den": 0, "insts": 0, "ns": set()})
    for inst in instances:
        d = pp[inst["persona"]]
        d["num"] += inst["repro"] * inst["full"]
        d["den"] += inst["full"]
        d["insts"] += 1
        d["ns"].add(inst["n"])
    for persona, d in pp.items():
        per_persona[persona] = {
            "reproducibility": (d["num"] / d["den"]) if d["den"] else None,
            "findings": d["den"], "instances": d["insts"], "n_values": sorted(d["ns"]),
        }
    return instances, agg_curves, per_persona


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshots", nargs="*", help="explicit findings-snapshot.json paths")
    ap.add_argument("--runs-dir", default=str(Path.home() / ".angel" / "runs"))
    ap.add_argument("--threshold", type=float, default=0.5, help="title overlap-coefficient to call a match")
    ap.add_argument("--severity", choices=["importantplus", "all"], default="importantplus")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    snaps = list(iter_snapshots(args.snapshots, None if args.snapshots else args.runs_dir))
    instances, agg_curves, per_persona = analyze(snaps, args.threshold, args.severity)

    if args.json:
        print(json.dumps({
            "params": {"threshold": args.threshold, "severity": args.severity},
            "coverage": {"multiball_snapshots": len(snaps),
                         "persona_instances": len(instances)},
            "recall_curve_by_n": {
                str(n): {"instances": c["instances"], "findings": c["findings"],
                         "recall": {str(k): v for k, v in c["recall"].items()}}
                for n, c in sorted(agg_curves.items())},
            "per_persona_reproducibility": per_persona,
        }, indent=2))
        return

    L = ["# NineAngel subsample-N analysis", ""]
    L.append(f"Params: title-overlap threshold **{args.threshold}**, severity **{args.severity}**.")
    L.append(f"Coverage: **{len(snaps)}** multiball snapshot(s), **{len(instances)}** persona instances "
             f"(a persona with ≥2 passes and ≥1 finding in one snapshot).")
    L.append("")
    if not instances:
        L.append("_No multiball data yet — `within_persona_runs` is null on all snapshots. "
                 "Curves accrue once default-ON multiball runs land._")
        print("\n".join(L))
        return

    L.append("## Recall vs N (how much of a persona's full finding set k passes recover)")
    L.append("")
    L.append("recall(1) = single-pass recall; recall(N)=100% by construction. Pick N where the curve flattens.")
    L.append("")
    for n in sorted(agg_curves):
        c = agg_curves[n]
        cells = "  ".join(f"k={k}: {100*v:.0f}%" for k, v in c["recall"].items() if v is not None)
        L.append(f"- **N={n}** ({c['instances']} instances, {c['findings']} findings): {cells}")
        # marginal gain of the last pass, to flag plateau
        rc = c["recall"]
        if n >= 2 and rc.get(n - 1) is not None:
            gain = rc[n] - rc[n - 1]
            L.append(f"  - last-pass marginal gain (k={n-1}→{n}): +{100*gain:.0f} pts"
                     + ("  ← small gain: N could drop" if gain < 0.05 else ""))
    L.append("")
    L.append("## Per-persona reproducibility (recall(1) — fraction of passes a finding repeats in)")
    L.append("")
    L.append("Low = stochastic (multiball helps most); high = stable (small N suffices).")
    L.append("")
    L.append("| persona | reproducibility | findings | instances | N |")
    L.append("|---|--:|--:|--:|---|")
    for persona, d in sorted(per_persona.items(), key=lambda kv: (kv[1]["reproducibility"] or 0)):
        repro = f"{100*d['reproducibility']:.0f}%" if d["reproducibility"] is not None else "—"
        ns = ",".join(str(x) for x in d["n_values"])
        L.append(f"| {persona} | {repro} | {d['findings']} | {d['instances']} | {ns} |")
    print("\n".join(L))


if __name__ == "__main__":
    main()
