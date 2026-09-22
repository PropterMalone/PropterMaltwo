#!/usr/bin/env python3
"""Bounded two-level semantic reduction for ADR-20 oversized worksets."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from integration_common import atomic_json, estimate_tokens, load_json, norm_file, title_overlap

D = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("decision_validator_shards", D / "validate-integration-decisions.py")
validator = importlib.util.module_from_spec(spec); spec.loader.exec_module(validator)

TARGET = 16000
HARD = 24000
RUNNER_CLEANUP_EXIT = 75
SHARD_DEPTH_EXIT = 3
SHARD_RUNNER_CLEANUP_EXIT = 4


class RunnerCleanupError(RuntimeError):
    pass


def subset(workset, candidates):
    ids = {c["id"] for c in candidates}
    value = {"version": 1, "run": workset["run"], "candidates": candidates,
             "candidate_edges": [e for e in workset.get("candidate_edges", [])
                                 if e.get("left") in ids and e.get("right") in ids],
             "noise_floor_discards": [], "pass_backends": workset.get("pass_backends", {}),
             "previous_cycle": workset.get("previous_cycle"), "metrics": {}}
    if "advisory_matches" in workset:
        # Advisory scores may focus a reducer only when both candidates already
        # share a deterministic shard. They never create shard connectivity.
        value["advisory_matches"] = [
            match for match in workset.get("advisory_matches", [])
            if match.get("left") in ids and match.get("right") in ids
        ]
    b, t = estimate_tokens(value); value["metrics"] = {"utf8_bytes": b, "tokens_estimate": t,
        "raw_records": sum(len(c.get("raw_source_ids", [])) for c in candidates),
        "retained_candidates": len(candidates), "noise_floor_discards": 0}
    return value


def components(workset):
    by_id = {c["id"]: c for c in workset["candidates"]}
    parent = {cid: cid for cid in by_id}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    def union(a, b):
        a, b = find(a), find(b)
        if a != b: parent[max(a, b)] = min(a, b)
    for edge in workset.get("candidate_edges", []):
        if edge.get("left") in parent and edge.get("right") in parent:
            union(edge["left"], edge["right"])
    groups = defaultdict(list)
    for cid in sorted(by_id): groups[find(cid)].append(by_id[cid])
    out = []
    for group in groups.values():
        if subset(workset, group)["metrics"]["tokens_estimate"] <= TARGET:
            out.append(group); continue
        # Preserve components when possible; an oversized component is cut only at
        # persona boundaries, with the final reducer adjudicating cross-shard overlap.
        lanes = defaultdict(list)
        for c in group: lanes[c.get("persona")].append(c)
        if len(lanes) == 1:
            lane = next(iter(lanes.values()))
            out.extend([[c] for c in lane])
        else:
            out.extend(lanes[k] for k in sorted(lanes))
    return out


def pack(workset):
    packs, current = [], []
    for component in sorted(components(workset), key=lambda g: g[0]["id"]):
        proposal = current + component
        if current and subset(workset, proposal)["metrics"]["tokens_estimate"] > TARGET:
            packs.append(current); current = list(component)
        else:
            current = proposal
        if subset(workset, current)["metrics"]["tokens_estimate"] > HARD:
            raise OverflowError(f"one shard exceeds {HARD} estimated tokens")
    if current: packs.append(current)
    return [subset(workset, p) for p in packs]


def call_reducer(workset_path, out_dir, mandate, schema, backend="auto",
                 runner_identity=None):
    out_dir.mkdir(parents=True, exist_ok=True)
    for attempt in (1, 2):
        attempt_dir = out_dir / f"attempt-{attempt}"
        command = [sys.executable, str(D / "run-reducer-sandbox.py"),
            "--mandate", str(mandate), "--workset", str(workset_path), "--schema", str(schema),
            "--output-dir", str(attempt_dir), "--timeout", "600", "--backend", backend]
        if runner_identity:
            command += ["--expected-identity", runner_identity]
        result = subprocess.run(command, text=True, capture_output=True)
        if result.returncode == RUNNER_CLEANUP_EXIT:
            raise RunnerCleanupError("runner cleanup failed; refusing another reducer attempt")
        decisions_path = attempt_dir / "integration-decisions.json"
        if result.returncode == 0 and decisions_path.is_file():
            workset = load_json(workset_path); decisions = load_json(decisions_path)
            if not validator.validate(workset, decisions, D.parent / "schemas"):
                return decisions, load_json(attempt_dir / "integration-telemetry.json")
    raise RuntimeError(f"reducer failed twice for {workset_path.name}")


def aggregate_telemetry(rows, level_counts):
    total = lambda key: sum(row.get(key) or 0 for row in rows)
    return {"version": 1, "endpoint": rows[0].get("endpoint"),
            "auth": rows[0].get("auth"), "model": rows[0].get("model"),
            "request_count": None, "turn_count": total("turn_count"),
            "tool_policy": "disabled-fail-closed", "tool_events": total("tool_events"),
            "blocked_tool_events": total("blocked_tool_events"),
            "input_tokens": total("input_tokens"), "output_tokens": total("output_tokens"),
            "cached_input_tokens": total("cached_input_tokens"),
            "reasoning_output_tokens": total("reasoning_output_tokens"),
            "total_tokens": total("total_tokens"), "duration_ms": total("duration_ms"),
            "response_status": "completed",
            # ``shards`` is retained for ADR-22 history, but now counts every
            # shard-reduction turn rather than only the first level.
            "shards": sum(level_counts),
            "initial_shard_count": level_counts[0],
            "shard_level_counts": level_counts,
            "final_reconciliation_turns": 1}


def compact_candidate(shard_i, finding_i, finding, candidates):
    sources = [candidates[cid] for cid in finding["source_candidate_ids"]]
    canonical = candidates[finding["canonical_source_id"]]
    support = sorted({p for source in sources for p in source.get("support_passes", [])})
    return {"id": f"c_shard_{shard_i:03d}_{finding_i:03d}", "persona": "integration_shard",
        "severity": finding["severity"], "title": finding["title"], "effort": finding.get("effort"),
        "file": finding.get("file", canonical.get("file")), "line": finding.get("line", canonical.get("line")),
        "description": finding["summary"], "raw_text": finding["summary"],
        "raw_source_ids": sorted({rid for s in sources for rid in s.get("raw_source_ids", [])}),
        "support_passes": support, "support_tag": None, "support_drift": None,
        "severity_ceiling": {"state": "none", "value": None, "policy": None},
        "reconciliation_status": "shard-reduced",
        "origin_candidate_ids": sorted({origin for source in sources
                                         for origin in source.get("origin_candidate_ids", [source["id"]])}),
        "origin_canonical_id": canonical.get("origin_canonical_id", canonical["id"])}


def compact_edges(candidates):
    edges = []
    for i, left in enumerate(candidates):
        for right in candidates[i + 1:]:
            same_file = norm_file(left.get("file")) and norm_file(left.get("file")) == norm_file(right.get("file"))
            overlap = title_overlap(left.get("title"), right.get("title"))
            if (same_file and overlap >= .35) or overlap >= .7:
                edges.append({"left": left["id"], "right": right["id"],
                              "reasons": ["post-shard-overlap"]})
    return edges


def expand_refs(rows, field, cmap):
    """Expand compact candidate references to the original workset IDs."""
    expanded = []
    for item in rows:
        row = dict(item)
        row[field] = sorted({origin for cid in item[field]
                             for origin in cmap[cid]["origin_candidate_ids"]})
        expanded.append(row)
    return expanded


def expand(final, compact, prior_exclusions, prior_derived=None,
           prior_notes=None, prior_registry=None):
    cmap = {c["id"]: c for c in compact["candidates"]}
    findings = []
    for finding in final["findings"]:
        sources = [cmap[cid] for cid in finding["source_candidate_ids"]]
        canonical = cmap[finding["canonical_source_id"]]
        row = dict(finding)
        row["source_candidate_ids"] = sorted({x for c in sources for x in c["origin_candidate_ids"]})
        row["canonical_source_id"] = canonical["origin_canonical_id"]
        row["derived_from_candidate_ids"] = sorted({x for cid in finding.get("derived_from_candidate_ids", [])
                                                     for x in cmap[cid]["origin_candidate_ids"]})
        findings.append(row)
    exclusions = list(prior_exclusions)
    for item in final.get("excluded_candidates", []):
        for cid in cmap[item["candidate_id"]]["origin_candidate_ids"]:
            exclusions.append({"candidate_id": cid, "reason": item["reason"],
                               "explanation": item["explanation"]})
    derived = list(prior_derived or [])
    derived.extend(expand_refs(final.get("derived_records", []),
                               "derived_from_candidate_ids", cmap))
    registry = list(prior_registry or [])
    registry.extend(expand_refs(final.get("registry_updates", []),
                                "source_candidate_ids", cmap))
    # A shard-level registry proposal only survives if its source survived the
    # global pass as one final finding. This preserves useful learning without
    # letting a globally excluded shard finding crash deterministic rendering.
    final_owner = {cid: finding["decision_id"] for finding in findings
                   for cid in finding["source_candidate_ids"]}
    registry = [row for row in registry
                if row["source_candidate_ids"]
                and all(cid in final_owner for cid in row["source_candidate_ids"])
                and len({final_owner[cid] for cid in row["source_candidate_ids"]}) == 1]
    return {"version": 1, "producer": "reducer", "degraded_reason": None,
            "findings": findings, "excluded_candidates": exclusions,
            "derived_records": derived,
            "integration_notes": list(prior_notes or []) + final.get("integration_notes", []),
            "registry_updates": registry}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir"); ap.add_argument("--mandate", required=True); ap.add_argument("--schema", required=True)
    ap.add_argument("--backend", choices=("codex",), required=True)
    ap.add_argument("--runner-identity", required=True)
    args = ap.parse_args(); run_dir = Path(args.run_dir).resolve()
    original = load_json(run_dir / "integration-workset.json")
    root = run_dir / "integration-shards"; root.mkdir(exist_ok=True)
    candidates = {c["id"]: c for c in original["candidates"]}
    compact_candidates, exclusions, telemetry = [], [], []
    prior_derived, prior_notes, prior_registry = [], [], []
    try:
        shards = pack(original)
        level_counts = [len(shards)]
        for i, shard in enumerate(shards, 1):
            sdir = root / f"shard-{i:03d}"; sdir.mkdir(exist_ok=True)
            atomic_json(sdir / "workset.json", shard)
            decisions, usage = call_reducer(sdir / "workset.json", sdir, Path(args.mandate), Path(args.schema), args.backend, args.runner_identity)
            telemetry.append(usage); exclusions.extend(decisions["excluded_candidates"])
            prior_derived.extend(decisions.get("derived_records", []))
            prior_notes.extend(decisions.get("integration_notes", []))
            prior_registry.extend(decisions.get("registry_updates", []))
            for j, finding in enumerate(decisions["findings"], 1):
                compact_candidates.append(compact_candidate(i, j, finding, candidates))
        compact = subset(original, compact_candidates)
        compact["candidate_edges"] = compact_edges(compact_candidates)
        compact["noise_floor_discards"] = []
        compact["metrics"]["tokens_estimate"] = estimate_tokens(compact)[1]
        if compact["metrics"]["tokens_estimate"] > HARD:
            # One further bounded layer. Origin fields are flattened at each hop, so
            # final expansion still resolves directly to the original candidates.
            level2_candidates, level2_exclusions = [], []
            level2_map = {c["id"]: c for c in compact["candidates"]}
            second_level_shards = pack(compact)
            level_counts.append(len(second_level_shards))
            for i, shard in enumerate(second_level_shards, 1):
                sdir = root / "level-2" / f"shard-{i:03d}"; sdir.mkdir(parents=True, exist_ok=True)
                atomic_json(sdir / "workset.json", shard)
                decisions, usage = call_reducer(sdir / "workset.json", sdir, Path(args.mandate), Path(args.schema), args.backend, args.runner_identity)
                telemetry.append(usage)
                prior_derived.extend(expand_refs(decisions.get("derived_records", []),
                                                 "derived_from_candidate_ids", level2_map))
                prior_notes.extend(decisions.get("integration_notes", []))
                prior_registry.extend(expand_refs(decisions.get("registry_updates", []),
                                                  "source_candidate_ids", level2_map))
                for exclusion in decisions["excluded_candidates"]:
                    for cid in level2_map[exclusion["candidate_id"]]["origin_candidate_ids"]:
                        level2_exclusions.append({"candidate_id": cid, "reason": exclusion["reason"],
                                                  "explanation": exclusion["explanation"]})
                for j, finding in enumerate(decisions["findings"], 1):
                    level2_candidates.append(compact_candidate(i, j, finding, level2_map))
            exclusions.extend(level2_exclusions)
            compact = subset(compact, level2_candidates)
            compact["candidate_edges"] = compact_edges(level2_candidates)
            compact["metrics"]["tokens_estimate"] = estimate_tokens(compact)[1]
            if compact["metrics"]["tokens_estimate"] > HARD:
                raise OverflowError("compact final workset exceeds hard budget after two levels")
        atomic_json(root / "final-workset.json", compact)
        final, usage = call_reducer(root / "final-workset.json", root / "final", Path(args.mandate), Path(args.schema), args.backend, args.runner_identity)
        telemetry.append(usage)
        expanded = expand(final, compact, exclusions, prior_derived,
                          prior_notes, prior_registry)
        errors = validator.validate(original, expanded, D.parent / "schemas")
        if errors: raise RuntimeError("expanded decisions invalid: " + "; ".join(errors))
        atomic_json(run_dir / "integration-decisions.json", expanded)
        atomic_json(run_dir / "integration-telemetry.json",
                    aggregate_telemetry(telemetry, level_counts))
    except RunnerCleanupError as exc:
        print(f"shard-integration: {exc}", file=sys.stderr)
        raise SystemExit(SHARD_RUNNER_CLEANUP_EXIT)
    except OverflowError as exc:
        print(f"shard-integration: {exc}", file=sys.stderr)
        raise SystemExit(SHARD_DEPTH_EXIT)
    except Exception as exc:
        print(f"shard-integration: {exc}", file=sys.stderr); raise SystemExit(1)


if __name__ == "__main__": main()
