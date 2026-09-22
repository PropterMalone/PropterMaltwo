#!/usr/bin/env python3
"""Validate ADR-20 decisions against their workset, or emit a safe union."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from integration_common import (DEGRADED_REASONS, EFFORTS, EVIDENCE,
                                EXCLUSION_REASONS, SEV_RANK, SEVERITIES,
                                append_progress, atomic_json, load_json,
                                norm_file)

EFFORT_RANK = {None: 0, "trivial": 1, "moderate": 2, "significant": 3}
COMMAND_SHAPED = re.compile(
    r"(?:^|\n)\s*(?:\$\s*)?(?:sudo\s+)?(?:bash|sh|zsh|fish|python\d*|node|npm|npx|"
    r"pnpm|yarn|cargo|go|make|curl|wget|git|rm|cp|mv|chmod|docker|kubectl)\b|"
    r"(?:&&|\|\||;\s*(?:sudo\s+)?(?:bash|sh|python|node|rm|curl|wget)\b)", re.I)


def schema_errors(document, schema_path: Path):
    try:
        import jsonschema
    except ImportError:
        return []
    validator = jsonschema.Draft202012Validator(load_json(schema_path))
    return [f"schema {'.'.join(str(x) for x in e.absolute_path) or '<root>'}: {e.message}"
            for e in sorted(validator.iter_errors(document), key=lambda x: list(x.absolute_path))]


def validate(workset, decisions, schema_dir=None):
    errors = []
    if schema_dir:
        errors += schema_errors(workset, Path(schema_dir) / "integration-workset-v1.json")
        errors += schema_errors(decisions, Path(schema_dir) / "integration-decisions-v1.json")

    candidates = {c.get("id"): c for c in workset.get("candidates", []) if c.get("id")}
    if len(candidates) != len(workset.get("candidates", [])):
        errors.append("workset candidate IDs are missing or duplicated")
    if decisions.get("producer") == "reducer" and decisions.get("degraded_reason") is not None:
        errors.append("reducer output must have degraded_reason=null")
    if decisions.get("producer") == "deterministic-union" and decisions.get("degraded_reason") not in DEGRADED_REASONS:
        errors.append("deterministic-union requires an allowed degraded_reason")

    primary, excluded, ranks, decision_ids = {}, {}, set(), set()
    previous_ids = {x.get("id") for x in (workset.get("previous_cycle") or [])}
    for i, finding in enumerate(decisions.get("findings", [])):
        where = f"findings[{i}]"
        did = finding.get("decision_id")
        if not did or did in decision_ids:
            errors.append(f"{where}: decision_id is missing or duplicated")
        decision_ids.add(did)
        sources = finding.get("source_candidate_ids") or []
        for cid in sources:
            if cid not in candidates:
                errors.append(f"{where}: unknown source candidate {cid}")
            elif cid in primary:
                errors.append(f"{where}: candidate {cid} already used by {primary[cid]}")
            primary[cid] = did
        if finding.get("canonical_source_id") not in sources:
            errors.append(f"{where}: canonical_source_id is not in source_candidate_ids")
        rank = finding.get("priority_rank")
        if rank in ranks:
            errors.append(f"{where}: duplicate priority_rank {rank}")
        ranks.add(rank)
        if finding.get("severity") not in SEVERITIES:
            errors.append(f"{where}: invalid severity")
        if finding.get("effort") not in (*EFFORTS, None):
            errors.append(f"{where}: invalid effort")
        if finding.get("evidence") not in EVIDENCE:
            errors.append(f"{where}: invalid evidence")
        if not str(finding.get("title") or "").strip() or not str(finding.get("summary") or "").strip():
            errors.append(f"{where}: title and summary are required")
        hint = finding.get("repro_hint")
        if hint and COMMAND_SHAPED.search(hint):
            errors.append(f"{where}: repro_hint is command-shaped")
        prev = finding.get("previous_finding_id")
        if prev and prev not in previous_ids:
            errors.append(f"{where}: unknown previous_finding_id {prev}")

        source_rows = [candidates[cid] for cid in sources if cid in candidates]
        max_effort = max((EFFORT_RANK.get(c.get("effort"), 0) for c in source_rows), default=0)
        if EFFORT_RANK.get(finding.get("effort"), 0) < max_effort and not str(finding.get("effort_reason") or "").strip():
            errors.append(f"{where}: effort understates a source without effort_reason")
        allowed_locations = {(norm_file(c.get("file")), str(c.get("line") or "")) for c in source_rows}
        canon = candidates.get(finding.get("canonical_source_id"), {})
        final_loc = (norm_file(finding.get("file", canon.get("file"))),
                     str(finding.get("line", canon.get("line")) or ""))
        if source_rows and final_loc not in allowed_locations:
            errors.append(f"{where}: location is not one of its source locations")
        for source in source_rows:
            ceiling = source.get("severity_ceiling") or {}
            if ceiling.get("state") == "unparsed":
                errors.append(f"{where}: source {source['id']} has an unparsed severity ceiling")
            if ceiling.get("state") == "detected":
                cap = ceiling.get("value")
                if cap not in SEVERITIES or SEV_RANK.get(finding.get("severity"), 0) > SEV_RANK.get(cap, 0):
                    errors.append(f"{where}: severity exceeds source {source['id']} ceiling {cap}")

    for i, item in enumerate(decisions.get("excluded_candidates", [])):
        cid, reason = item.get("candidate_id"), item.get("reason")
        if cid not in candidates:
            errors.append(f"excluded_candidates[{i}]: unknown candidate {cid}")
        if cid in primary or cid in excluded:
            errors.append(f"excluded_candidates[{i}]: candidate {cid} is accounted more than once")
        excluded[cid] = reason
        if reason not in EXCLUSION_REASONS or not str(item.get("explanation") or "").strip():
            errors.append(f"excluded_candidates[{i}]: allowed reason and explanation required")

    missing = sorted(set(candidates) - set(primary) - set(excluded))
    if missing:
        errors.append(f"unaccounted candidates: {', '.join(missing)}")
    for i, record in enumerate(decisions.get("derived_records", [])):
        refs = record.get("derived_from_candidate_ids") or []
        if not refs or any(cid not in candidates for cid in refs):
            errors.append(f"derived_records[{i}]: sources must all exist")
    for i, item in enumerate(decisions.get("registry_updates", [])):
        required = ("field", "kind", "why", "source", "severity", "status", "source_candidate_ids")
        if any(not item.get(k) for k in required) or item.get("source") not in ("pii", "deanon") or item.get("status") != "candidate":
            errors.append(f"registry_updates[{i}]: invalid fixed registry shape")
        if any(cid not in candidates for cid in item.get("source_candidate_ids", [])):
            errors.append(f"registry_updates[{i}]: unknown source candidate")
    return errors


def deterministic_union(workset, reason):
    order = sorted(workset.get("candidates", []), key=lambda c: (
        -SEV_RANK.get(c.get("severity"), 0), c.get("persona") or "",
        norm_file(c.get("file")) or "", str(c.get("line") or ""), c.get("id") or ""))
    findings = []
    for rank, candidate in enumerate(order, 1):
        findings.append({
            "decision_id": f"union-{rank}", "source_candidate_ids": [candidate["id"]],
            "canonical_source_id": candidate["id"], "title": candidate.get("title") or "Untitled finding",
            "summary": candidate.get("description") or candidate.get("raw_text") or candidate.get("title") or "Preserved source finding.",
            "severity": candidate.get("severity") or "noted", "severity_reason": "source severity preserved by deterministic union",
            "effort": candidate.get("effort"), "effort_reason": None,
            "evidence": "inference", "priority_rank": rank,
            "loop_status": None, "previous_finding_id": None, "consistency_shaped": False,
            "causal_claim": None, "repro_hint": None, "file": candidate.get("file"),
            "line": candidate.get("line"), "derived_from_candidate_ids": [],
        })
    return {"version": 1, "producer": "deterministic-union", "degraded_reason": reason,
            "findings": findings, "excluded_candidates": [], "derived_records": [],
            "integration_notes": ["Semantic deduplication and registry learning were unavailable."],
            "registry_updates": []}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workset")
    ap.add_argument("decisions", nargs="?")
    ap.add_argument("--write-union", metavar="PATH")
    ap.add_argument("--reason", choices=DEGRADED_REASONS)
    args = ap.parse_args()
    workset = load_json(Path(args.workset))
    if args.write_union:
        if not args.reason:
            raise SystemExit("--write-union requires --reason")
        decisions = deterministic_union(workset, args.reason)
        atomic_json(Path(args.write_union), decisions)
    elif args.decisions:
        decisions = load_json(Path(args.decisions))
    else:
        raise SystemExit("decisions path or --write-union is required")
    errors = validate(workset, decisions, Path(__file__).resolve().parent.parent / "schemas")
    if errors:
        print("\n".join(f"- {error}" for error in errors), file=sys.stderr)
        raise SystemExit(2)
    run_dir = Path(workset.get("run", {}).get("run_dir") or Path(args.workset).parent)
    decision_path = Path(args.write_union or args.decisions).resolve()
    if decision_path.parent == run_dir.resolve():
        append_progress(run_dir, "decisions-validated")
    print(f"valid: {len(decisions['findings'])} findings; {len(decisions['excluded_candidates'])} exclusions")


if __name__ == "__main__":
    main()
