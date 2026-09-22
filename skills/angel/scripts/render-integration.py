#!/usr/bin/env python3
"""Render ADR-20 decisions into byte-consistent report/snapshot artifacts."""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from integration_common import (EFFORTS, SEV_RANK, SEVERITIES, append_progress,
                                atomic_json, atomic_text, load_json, norm_file,
                                normalize_named_reasons)

_D = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("decision_validator", _D / "validate-integration-decisions.py")
_validator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_validator)

DISPLAY_SEV = {name: name.title() for name in SEVERITIES}


def decision_support(source_rows, denominators):
    grouped = defaultdict(set)
    for source in source_rows:
        grouped[source.get("persona")].update(source.get("support_passes") or [])
    out = {}
    for persona in sorted(grouped):
        n = (denominators or {}).get(persona)
        if n:
            out[persona] = [len(grouped[persona]), n]
    return out


def anchored(finding):
    if finding["evidence"] in ("cited-spec", "code-site"):
        return True
    if len(finding["personas"]) >= 2:
        return True
    return any(k >= 2 for k, _n in finding.get("decision_support", {}).values())


def derive_verdict(findings):
    if any(f["severity"] == "critical" and f["anchored"] for f in findings):
        return "CHANGES REQUIRED"
    if any(f["severity"] in ("critical", "important") for f in findings):
        return "CHANGES RECOMMENDED"
    if findings:
        return "APPROVED (with suggestions)"
    return "APPROVED"


def eligible_for_verification(finding):
    if not finding.get("causal_claim"):
        return False
    if finding["severity"] == "critical":
        return True
    if finding["severity"] != "important":
        return False
    if finding.get("consistency_shaped"):
        return True
    support = list((finding.get("decision_support") or {}).values())
    return (finding.get("evidence") != "cited-spec" and bool(support)
            and all(k <= n // 2 for k, n in support))


def usage_resources(run_dir, personas):
    entries, persona_entries = [], []
    path = run_dir / "usage.jsonl"
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            entries.append(item)
            if item.get("phase") == "persona":
                persona_entries.append(item)
    by_persona = {}
    for item in persona_entries:
        by_persona[item.get("name")] = item
    rows = []
    for persona in personas:
        item = by_persona.get(persona, {})
        rows.append({"name": persona, "tool_calls": item.get("tool_uses"),
                     "duration_s": ((item.get("duration_ms") or 0) / 1000
                                    if item.get("duration_ms") is not None else None),
                     "input_tokens": None, "output_tokens": None,
                     "total_tokens": item.get("total_tokens")})
    starts, ends = [], []
    for item in entries:
        for key, target in (("started_at", starts), ("ended_at", ends)):
            try:
                target.append(datetime.fromisoformat(item[key].replace("Z", "+00:00")))
            except (KeyError, TypeError, ValueError, AttributeError):
                # AttributeError: a null timestamp (a --failed stub with no
                # start) is `None`, not a string — skip it like a missing key.
                pass
    wall = int((max(ends) - min(starts)).total_seconds()) if starts and ends else None
    return {"personas": rows, "reader": None, "total_input_tokens": None,
            "total_output_tokens": None, "total_wall_clock_s": wall}


def build_artifacts(workset, decisions, run_dir):
    candidates = {c["id"]: c for c in workset["candidates"]}
    # IDs depend only on the sorted primary source set, never priority/display order.
    ordered_for_ids = sorted(decisions["findings"], key=lambda d: tuple(sorted(d["source_candidate_ids"])))
    final_id = {d["decision_id"]: f"f{i}" for i, d in enumerate(ordered_for_ids, 1)}
    candidate_to_final = {cid: final_id[d["decision_id"]]
                          for d in decisions["findings"] for cid in d["source_candidate_ids"]}

    findings = []
    denominators = workset["run"].get("pass_denominators") or {}
    for decision in decisions["findings"]:
        sources = [candidates[cid] for cid in decision["source_candidate_ids"]]
        canonical = candidates[decision["canonical_source_id"]]
        support = decision_support(sources, denominators)
        item = {
            "id": final_id[decision["decision_id"]], "severity": decision["severity"],
            "title": decision["title"], "file": decision.get("file", canonical.get("file")),
            "line": decision.get("line", canonical.get("line")), "effort": decision.get("effort"),
            "personas": sorted({c["persona"] for c in sources}), "evidence": decision["evidence"],
            "pass_support": None, "verification": None, "summary": decision["summary"],
            "source_candidate_ids": sorted(decision["source_candidate_ids"]),
            "derived_from_candidate_ids": decision.get("derived_from_candidate_ids") or [],
            "decision_support": support, "priority_rank": decision["priority_rank"],
            "consistency_shaped": decision.get("consistency_shaped", False),
            "causal_claim": decision.get("causal_claim"), "repro_hint": decision.get("repro_hint"),
            "loop_status": decision.get("loop_status"),
            "previous_finding_id": decision.get("previous_finding_id"),
        }
        item["anchored"] = anchored(item)
        findings.append(item)
    findings.sort(key=lambda x: (x["priority_rank"], x["id"]))
    verdict = derive_verdict(findings)
    verify = [f for f in findings if eligible_for_verification(f)][:8]
    verify_queue = [{"id": f["id"], "severity": f["severity"], "title": f["title"],
                     "file": f["file"], "line": f["line"], "claim": f["causal_claim"],
                     "repro_hint": f["repro_hint"]} for f in verify]

    registry = []
    for update in decisions.get("registry_updates", []):
        ids = {candidate_to_final[cid] for cid in update["source_candidate_ids"]}
        if len(ids) != 1:
            raise ValueError(f"registry update crosses final findings: {sorted(ids)}")
        registry.append({k: update[k] for k in ("field", "kind", "why", "source", "severity", "status")})
        registry[-1]["finding_id"] = next(iter(ids))

    run = workset["run"]
    degraded = decisions["producer"] == "deterministic-union"
    snapshot = {
        "version": 3, "decision_schema_version": decisions["version"],
        "project": run["project"], "date": run["date"], "mode": run["mode"],
        "verdict": verdict, "personas_run": run.get("personas_run") or [],
        "personas_dropped": run.get("personas_dropped") or [],
        "personas_failed": run.get("personas_failed") or [], "preflight": run.get("preflight") or {},
        "reader_mode": run.get("reader_mode") or "off", "findings": findings,
        "resource_consumption": usage_resources(run_dir, run.get("personas_run") or []),
        "codebase": run.get("codebase") or {}, "multiball": run.get("multiball"),
        "within_persona_runs": None, "verify_queue": verify_queue,
        "integration_degraded": degraded,
        "integration_degraded_reason": decisions.get("degraded_reason"),
        "excluded_candidates": decisions.get("excluded_candidates") or [],
        "noise_floor_discards": workset.get("noise_floor_discards") or [],
        "derived_records": decisions.get("derived_records") or [],
        "integration_notes": decisions.get("integration_notes") or [],
    }
    return snapshot, registry


def fmt_location(finding):
    if not finding.get("file"):
        return "location omitted (architectural finding)"
    return f"`{finding['file']}:{finding['line']}`" if finding.get("line") else f"`{finding['file']}`"


def render_report(snapshot):
    findings = snapshot["findings"]
    counts = Counter(f["severity"] for f in findings)
    efforts = Counter(f.get("effort") for f in findings if f.get("effort"))
    preflight = ", ".join(f"{k}: {v}" for k, v in snapshot["preflight"].items()) or "not recorded"
    lines = [f"# Code Review — {snapshot['verdict']}", "",
             f"**Personas**: {', '.join(snapshot['personas_run']) or 'none'}",
             f"**Files reviewed**: {snapshot.get('codebase', {}).get('files')}",
             f"**Pre-flight**: {preflight}",
             f"**Findings**: {counts['critical']} critical, {counts['important']} important, {counts['minor']} minor, {counts['noted']} noted",
             f"**Effort**: {efforts['trivial']} trivial · {efforts['moderate']} moderate · {efforts['significant']} significant"]
    if snapshot.get("multiball"):
        lines.append(f"**Mode**: multiball N={snapshot['multiball']}")
    if snapshot.get("personas_dropped"):
        dropped = normalize_named_reasons(snapshot["personas_dropped"],
                                          "personas_dropped entry", strict=False)
        lines.append("**Skipped**: " + ", ".join(
            f"{x['name']} ({x['reason']})" for x in dropped))
    lines += [""]
    if snapshot["integration_degraded"]:
        lines += ["## DEGRADED INTEGRATION", "",
                  f"Reason: `{snapshot['integration_degraded_reason']}`. The deterministic union preserved {len(findings)} candidates as {len(findings)} findings; semantic deduplication and registry updates were not produced.", "",
                  "Retry: `scripts/integrate-run.sh " + str(snapshot.get("run_dir", "<RUN_DIR>")) + " --retry-reducer`", ""]
    material_exclusions = [x for x in snapshot["excluded_candidates"] if x.get("reason") in
                           ("instruction-shaped-content-redacted", "malformed-nonfinding")]
    if material_exclusions:
        lines += ["## Coverage exclusions", ""]
        lines += [f"- `{x.get('candidate_id')}` — {x.get('reason')}: {x.get('explanation')}" for x in material_exclusions]
        lines.append("")
    if snapshot.get("personas_failed"):
        failed = normalize_named_reasons(snapshot["personas_failed"],
                                         "personas_failed entry", strict=False)
        lines += ["## Coverage Gaps", "", "The following personas did not contribute complete findings:", ""]
        lines += [f"- **{x['name']}** — {x['reason']}" for x in failed]
        lines.append("")
    lines += ["---", "", "## Top 5", ""]
    for i, finding in enumerate(findings[:5], 1):
        effort = f" `[{finding['effort']}]`" if finding.get("effort") else ""
        lines.append(f"{i}. **{finding['title']}**{effort} — {fmt_location(finding)} — {finding['summary']} *({len(finding['personas'])} personas)*")
    if not findings:
        lines.append("No findings.")
    lines += [""]
    if snapshot["integration_degraded"]:
        lines += ["## Full candidate ledger", "",
                  "This report intentionally stops after the preliminary Top 5 because the semantic reducer did not run. The complete lossless union remains in `findings-snapshot.json` for retry and audit.", "",
                  f"Ledger size: {len(findings)} candidates ({counts['critical']} critical, {counts['important']} important, {counts['minor']} minor, {counts['noted']} noted).", ""]
    else:
        for severity in SEVERITIES:
            rows = [f for f in findings if f["severity"] == severity]
            if not rows:
                continue
            lines += [f"## {DISPLAY_SEV[severity]}", ""]
            for finding in rows:
                effort = f" `[{finding['effort']}]`" if finding.get("effort") else ""
                unanchored = " **[unanchored]**" if severity == "critical" and not finding["anchored"] else ""
                lines.append(f"- **{finding['title']}**{effort}{unanchored} — {fmt_location(finding)} — {finding['summary']} *(caught by: {', '.join(finding['personas'])})*")
            lines.append("")
    lines += ["---", "", "## Resource Consumption", "",
              "| Persona | Tool Calls | Duration | Tokens |", "|---|---:|---:|---:|"]
    for row in snapshot["resource_consumption"]["personas"]:
        duration = "" if row["duration_s"] is None else f"{row['duration_s']:.1f}s"
        lines.append(f"| {row['name']} | {row['tool_calls'] if row['tool_calls'] is not None else ''} | {duration} | {row['total_tokens'] if row['total_tokens'] is not None else ''} |")
    lines += ["", "## Integration Notes", ""]
    notes = list(snapshot.get("integration_notes") or [])
    notes.append(f"Mechanical noise-floor discards: {len(snapshot['noise_floor_discards'])}.")
    if any(f["severity"] == "critical" and not f["anchored"] for f in findings):
        notes.append("One or more Critical findings are unanchored and do not drive the headline verdict.")
    lines += [f"- {note}" for note in notes] or ["- None."]
    lines += ["", f"*Review by NineAngel — {snapshot['date']}*", ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--workset")
    ap.add_argument("--decisions")
    ap.add_argument("--retry", action="store_true", help="allow the separately gated pristine degraded retry")
    args = ap.parse_args()
    run_dir = Path(args.run_dir).resolve()
    existing_path = run_dir / "findings-snapshot.json"
    if existing_path.is_file():
        existing = load_json(existing_path)
        verified = (run_dir / "verification").exists() or any(
            f.get("verification") for f in existing.get("findings", []) if isinstance(f, dict))
        dispositions = run_dir / "dispositions.json"
        disposed = False
        if dispositions.is_file():
            rows = load_json(dispositions)
            disposed = any(isinstance(v, dict) and v.get("disposition") != "no-record"
                           for k, v in rows.items() if k != "experiment")
        if verified or disposed:
            raise SystemExit("render-integration: enriched run is immutable; use integrate-run.sh --clone-retry")
        if args.retry and not existing.get("integration_degraded"):
            raise SystemExit("render-integration: --retry requires an existing degraded snapshot")
    workset = load_json(Path(args.workset) if args.workset else run_dir / "integration-workset.json")
    decisions = load_json(Path(args.decisions) if args.decisions else run_dir / "integration-decisions.json")
    errors = _validator.validate(workset, decisions, _D.parent / "schemas")
    if errors:
        raise SystemExit("render-integration: invalid decisions:\n" + "\n".join(f"- {x}" for x in errors))
    snapshot, registry = build_artifacts(workset, decisions, run_dir)
    snapshot["run_dir"] = str(run_dir)
    report = render_report(snapshot)
    atomic_text(run_dir / "report.md", report)
    append_progress(run_dir, "report-rendered")
    atomic_json(run_dir / "findings-snapshot.json", snapshot)
    append_progress(run_dir, "snapshot-rendered")
    if any(p in ("pii", "deanon") for p in snapshot["personas_run"]):
        atomic_json(run_dir / "registry-updates.json", registry)
    print(f"{snapshot['verdict']}: {len(snapshot['findings'])} findings; verify {len(snapshot['verify_queue'])}")


if __name__ == "__main__":
    main()
