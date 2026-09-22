#!/usr/bin/env python3
"""Build ADR-20 integration-workset.json from durable Markdown and run metadata."""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from integration_common import (SEV_RANK, append_progress, atomic_json, estimate_tokens,
                                exact_key, line_start, load_json, norm_file,
                                strict_match_score, title_overlap)
from jev_reconciliation import PROMPT_VERSION, validate_artifact
from persona_aliases import build_persona_aliases, canon_persona

_spec = importlib.util.spec_from_file_location("parse_findings", SCRIPT_DIR / "parse-findings.py")
_parser = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_parser)
parse_lossless = _parser.parse_findings_lossless

PASS_RE = re.compile(r"^(?P<persona>.+?)[-_](?:p|pass)(?P<i>\d+)\.md$", re.I)
FAILED_RE = re.compile(r"<!--\s*angel-pass[^>]*\bfailed\b[^>]*-->", re.I)
BACKEND_RE = re.compile(r"<!--\s*angel-pass[^>]*\bbackend=(\S+?)(?=\s|-->)", re.I)
UNTRUSTED_PATTERNS = (
    ("override-directive", re.compile(r"\b(?:ignore|override|disregard)\b.{0,40}\b(?:instruction|prompt|rule)s?\b", re.I)),
    ("role-directive", re.compile(r"\byou are now\b|^\s*#{1,4}\s+your persona\b", re.I | re.M)),
    ("authority-claim", re.compile(r"\b(?:user|maintainer) (?:has )?(?:pre-)?authorized\b", re.I)),
    ("system-markup", re.compile(r"</?(?:system|developer|assistant|tool)>", re.I)),
)


def untrusted_flags(value):
    return sorted(name for name, pattern in UNTRUSTED_PATTERNS if pattern.search(value or ""))


def legacy_meta(run_dir: Path):
    snap = load_json(run_dir / "findings-snapshot.json")
    denominators = defaultdict(int)
    pdir = run_dir / "passes"
    if pdir.is_dir():
        aliases = build_persona_aliases(SCRIPT_DIR.parent)
        for path in pdir.glob("*.md"):
            match = PASS_RE.match(path.name)
            if match:
                persona = canon_persona(match.group("persona"), aliases)
                denominators[persona] = max(denominators[persona], int(match.group("i")))
    return {
        "version": 1, "integration_pipeline": "semantic-reducer-v1",
        "status": "ready", "run_dir": str(run_dir),
        "project_dir": None, "project": snap.get("project") or "historical",
        "date": snap.get("date"), "mode": snap.get("mode") or "full",
        "reader_mode": snap.get("reader_mode") or "off",
        "files_reviewed": (snap.get("codebase") or {}).get("files"),
        "preflight": snap.get("preflight") or {"test": "unknown", "build": "unknown", "lint": "unknown"},
        "multiball": snap.get("multiball"),
        "pass_denominators": dict(denominators), "personas_run": snap.get("personas_run") or [],
        "personas_dropped": snap.get("personas_dropped") or [],
        "personas_failed": snap.get("personas_failed") or [],
        "codebase": snap.get("codebase") or {"files": None, "lines": None},
        "previous_run_dir": None, "metadata_provenance": "historical-snapshot-adapter",
    }


def require_meta(run_dir: Path, allow_legacy=False):
    path = run_dir / "run-meta.json"
    meta = load_json(path) if path.is_file() else (legacy_meta(run_dir) if allow_legacy else None)
    if not meta:
        raise ValueError("missing run-meta.json; use record-run-meta.py before integration")
    if meta.get("integration_pipeline") != "semantic-reducer-v1" or meta.get("status") != "ready":
        raise ValueError("run-meta.json is not ready semantic-reducer-v1 metadata")
    required = ("project", "date", "mode", "reader_mode", "preflight", "personas_run",
                "personas_dropped", "personas_failed", "codebase")
    missing = [key for key in required if meta.get(key) is None]
    if missing:
        raise ValueError(f"run-meta.json missing required fields: {', '.join(missing)}")
    return meta


def candidate_from_record(persona, record, status):
    return {
        "persona": persona,
        "severity": record.get("severity") or "noted",
        "title": record.get("title") or "Untitled finding",
        "effort": record.get("effort"),
        "file": record.get("file"), "line": record.get("line"),
        "description": record.get("description") or record.get("raw_text") or "",
        "raw_text": record.get("raw_text") or "",
        "raw_source_ids": [], "support_passes": [],
        "support_tag": record.get("support_tag"), "support_drift": None,
        "severity_ceiling": record.get("severity_ceiling") or
                            {"state": "none", "value": None, "policy": None},
        "reconciliation_status": status,
        "untrusted_content_flags": untrusted_flags((record.get("raw_text") or "") + "\n" +
                                                   (record.get("description") or "")),
    }


def parse_passes(run_dir, aliases):
    by_persona, records, discards, backends, failed = defaultdict(list), [], [], {}, []
    pdir = run_dir / "passes"
    if not pdir.is_dir():
        return by_persona, records, discards, backends, failed
    for path in sorted(pdir.glob("*.md")):
        match = PASS_RE.match(path.name)
        if not match:
            continue
        persona = canon_persona(match.group("persona"), aliases)
        stem = path.stem
        text = path.read_text(encoding="utf-8", errors="replace")
        if FAILED_RE.search(text):
            failed.append({"persona": persona, "pass": int(match.group("i")), "reason": "failed-pass-stub"})
            continue
        parsed = parse_lossless(text, stem)
        if parsed["status"] == "no-structure":
            failed.append({"persona": persona, "pass": int(match.group("i")), "reason": "unparseable-pass"})
            continue
        backend = BACKEND_RE.search(text)
        backends[stem] = backend.group(1).lower() if backend else "unknown"
        for row in parsed["records"]:
            row = dict(row); row["persona"] = persona
            records.append(row)
        for row in parsed["findings"]:
            row = dict(row); row["persona"] = persona
            by_persona[persona].append(row)
        for row in parsed["discards"]:
            if row.get("file") and row.get("line"):
                raise ValueError(f"noise-floor discard has parsed location: {row['raw_source_id']}")
            discards.append({k: row.get(k) for k in
                             ("raw_source_id", "source_stem", "ordinal", "section",
                              "discard_rule", "raw_text")})
            discards[-1]["source_file"] = f"{row.get('source_stem')}.md"
            discards[-1]["rule"] = discards[-1].pop("discard_rule")
    return by_persona, records, discards, backends, failed


def assign_raw(candidates, raw_rows, denominator):
    unmatched = []
    for raw in raw_rows:
        scored = []
        for idx, candidate in enumerate(candidates):
            score = strict_match_score(raw, candidate)
            if score is not None:
                scored.append((score, idx))
        scored.sort(reverse=True)
        # A tie is ambiguous, not an excuse to force-bind.
        if not scored or (len(scored) > 1 and abs(scored[0][0] - scored[1][0]) < 1e-9):
            unmatched.append(raw)
            continue
        candidates[scored[0][1]]["raw_source_ids"].append(raw["raw_source_id"])
    for raw in unmatched:
        candidate = candidate_from_record(raw["persona"], raw, "recovered-unmatched")
        candidate["raw_source_ids"] = [raw["raw_source_id"]]
        candidates.append(candidate)
    for candidate in candidates:
        passes = sorted({rid.rsplit(":r", 1)[0] for rid in candidate["raw_source_ids"]})
        candidate["support_passes"] = passes
        recompute = [len(passes), denominator] if denominator else None
        tag = candidate.get("support_tag")
        if tag and recompute and tag != recompute:
            candidate["support_drift"] = {"tag": tag, "recompute": recompute}
    return candidates


def build_candidates(run_dir, meta, aliases, raw_union=False):
    raw_by_persona, raw_records, discards, backends, failed = parse_passes(run_dir, aliases)
    multiball = bool(raw_by_persona or (run_dir / "passes").is_dir())
    candidates = []
    if multiball:
        rdir = run_dir / "reconciled"
        personas = sorted(set(meta.get("personas_run") or []) | set(raw_by_persona))
        for persona in personas:
            rows = raw_by_persona.get(persona, [])
            if raw_union:
                lane = []
                for row in rows:
                    candidate = candidate_from_record(persona, row, "jev-shadow-raw")
                    candidate["raw_source_ids"] = [row["raw_source_id"]]
                    candidate["support_passes"] = [row["raw_source_id"].rsplit(":r", 1)[0]]
                    lane.append(candidate)
                candidates.extend(lane)
                continue
            view = rdir / f"{persona}.md"
            parsed = parse_lossless(view.read_text(encoding="utf-8", errors="replace"), f"reconciled-{persona}") if view.is_file() else None
            if parsed and parsed["status"] != "no-structure":
                lane = [candidate_from_record(persona, row, "reconciled") for row in parsed["findings"]]
                # Empty reconciled output with raw signals is a failed view, not a drop.
                if not lane and rows:
                    parsed = None
            if not parsed or parsed["status"] == "no-structure":
                groups = {}
                for row in rows:
                    key = exact_key(row)
                    if key not in groups:
                        groups[key] = candidate_from_record(persona, row, "union-fallback")
                    groups[key]["raw_source_ids"].append(row["raw_source_id"])
                    if SEV_RANK.get(row.get("severity"), 0) > SEV_RANK.get(groups[key]["severity"], 0):
                        groups[key]["severity"] = row["severity"]
                lane = list(groups.values())
                # IDs are already attached for union groups; assign_raw only fills support.
                for candidate in lane:
                    candidate["support_passes"] = sorted({rid.rsplit(":r", 1)[0]
                                                          for rid in candidate["raw_source_ids"]})
            else:
                lane = assign_raw(lane, rows, (meta.get("pass_denominators") or {}).get(persona))
                # A reconciled row that cannot be grounded in a raw record is not a
                # candidate. The unmatched raw record was recovered above, so keeping
                # this row as well would manufacture a source-less duplicate.
                lane = [candidate for candidate in lane if candidate["raw_source_ids"]]
            candidates.extend(lane)
    else:
        fdir = run_dir / "findings"
        for path in sorted(fdir.glob("*.md")) if fdir.is_dir() else []:
            persona = canon_persona(path.stem, aliases)
            parsed = parse_lossless(path.read_text(encoding="utf-8", errors="replace"), path.stem)
            if parsed["status"] == "no-structure":
                failed.append({"persona": persona, "reason": "unparseable-findings"})
                continue
            for row in parsed["records"]:
                row = dict(row); row["persona"] = persona; raw_records.append(row)
            for row in parsed["discards"]:
                discards.append({"raw_source_id": row["raw_source_id"], "source_file": path.name,
                                 "ordinal": row["ordinal"], "section": row["section"],
                                 "rule": row["discard_rule"], "raw_text": row["raw_text"]})
            for row in parsed["findings"]:
                candidate = candidate_from_record(persona, row, "single-pass")
                candidate["raw_source_ids"] = [row["raw_source_id"]]
                candidate["support_passes"] = []
                candidates.append(candidate)

    counters = defaultdict(int)
    candidates.sort(key=lambda c: (c["persona"], norm_file(c.get("file")) or "",
                                   line_start(c.get("line")) or 0, c.get("title") or "",
                                   c["raw_source_ids"][0] if c["raw_source_ids"] else ""))
    for candidate in candidates:
        counters[candidate["persona"]] += 1
        safe = re.sub(r"[^a-z0-9]+", "_", candidate["persona"].lower()).strip("_")
        candidate["id"] = f"c_{safe}_{counters[candidate['persona']]:03d}"
    return candidates, raw_records, discards, backends, failed


def edges(candidates):
    out = []
    for i, left in enumerate(candidates):
        for right in candidates[i + 1:]:
            reasons = []
            lf, rf = norm_file(left.get("file")), norm_file(right.get("file"))
            overlap = title_overlap(left.get("title"), right.get("title"))
            ll, rl = line_start(left.get("line")), line_start(right.get("line"))
            if lf and rf and lf == rf:
                reasons.append("same-file")
                if ll is not None and rl is not None and abs(ll - rl) <= 2:
                    reasons.append("line-distance<=2")
                if overlap >= 0.5:
                    reasons.append(f"title-overlap={overlap:.2f}")
            elif not lf and not rf and overlap >= 0.7:
                reasons.append(f"coordinate-less-title-overlap={overlap:.2f}")
            if len(reasons) >= 2 or (reasons and reasons[0].startswith("coordinate")):
                out.append({"left": left["id"], "right": right["id"], "reasons": reasons})
    return out


def previous_cycle(meta):
    value = meta.get("previous_run_dir")
    if not value:
        return None
    snap = load_json(Path(value) / "findings-snapshot.json")
    return [{k: row.get(k) for k in ("id", "severity", "title", "file", "line", "summary")}
            for row in snap.get("findings", []) if isinstance(row, dict)]


def advisory_matches(run_dir, candidates, threshold):
    if (not isinstance(threshold, (int, float)) or isinstance(threshold, bool) or
            threshold < 0 or threshold > 1):
        raise ValueError("Jev advisory threshold must be between 0 and 1")
    artifact = load_json(run_dir / "jev-reconciliation.json")
    _pairs, scored = validate_artifact(run_dir, artifact)
    candidate_by_raw = {}
    for candidate in candidates:
        if len(candidate["raw_source_ids"]) != 1:
            raise ValueError("Jev advisory matches require one candidate per raw finding")
        candidate_by_raw[candidate["raw_source_ids"][0]] = candidate["id"]
    matches = []
    for pair_id in sorted(scored):
        row = scored[pair_id]
        if row["score"] < threshold:
            continue
        left = candidate_by_raw.get(row["left_raw_source_id"])
        right = candidate_by_raw.get(row["right_raw_source_id"])
        if not left or not right or left == right:
            raise ValueError(f"Jev pair cannot map to distinct candidates: {pair_id}")
        matches.append({"left": left, "right": right, "score": row["score"],
                        "source": "jev", "prompt_version": PROMPT_VERSION})
    return matches


def build(run_dir: Path, allow_legacy=False, raw_union=False,
          jev_advisory_threshold=None):
    if jev_advisory_threshold is not None and not raw_union:
        raise ValueError("Jev advisory matches require --raw-union")
    meta = require_meta(run_dir, allow_legacy)
    aliases = build_persona_aliases(SCRIPT_DIR.parent)
    candidates, raw_records, discards, backends, failed = build_candidates(
        run_dir, meta, aliases, raw_union=raw_union)
    retained_ids = [rid for c in candidates for rid in c["raw_source_ids"]]
    discarded_ids = [d["raw_source_id"] for d in discards]
    all_ids = [r["raw_source_id"] for r in raw_records]
    if len(set(all_ids)) != len(all_ids):
        raise ValueError("duplicate raw_source_id in raw enumeration")
    accounted = retained_ids + discarded_ids
    if sorted(accounted) != sorted(all_ids) or len(accounted) != len(set(accounted)):
        missing = sorted(set(all_ids) - set(accounted))
        extra = sorted(set(accounted) - set(all_ids))
        raise ValueError(f"raw-ID accounting failure missing={missing} extra={extra}")
    run = {k: meta.get(k) for k in ("integration_pipeline", "run_dir", "project", "date",
           "mode", "reader_mode", "files_reviewed", "preflight", "multiball",
           "pass_denominators", "personas_run", "personas_dropped", "personas_failed", "codebase")}
    if raw_union:
        run["reconciliation_path"] = (
            "jev-shadow-advisory" if jev_advisory_threshold is not None
            else "jev-shadow")
    if failed:
        run["personas_failed"] = list(run.get("personas_failed") or []) + failed
    workset = {"version": 1, "run": run, "candidates": candidates,
               "candidate_edges": edges(candidates), "noise_floor_discards": discards,
               "pass_backends": backends, "previous_cycle": previous_cycle(meta)}
    if raw_union:
        workset["advisory_matches"] = (
            advisory_matches(run_dir, candidates, jev_advisory_threshold)
            if jev_advisory_threshold is not None else [])
    byte_count, token_estimate = estimate_tokens(workset)
    workset["metrics"] = {"utf8_bytes": byte_count, "tokens_estimate": token_estimate,
                          "raw_records": len(raw_records), "retained_candidates": len(candidates),
                          "noise_floor_discards": len(discards)}
    return workset


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--allow-legacy-meta", action="store_true")
    ap.add_argument("--raw-union", action="store_true")
    ap.add_argument("--jev-advisory-threshold", type=float)
    ap.add_argument("--output")
    args = ap.parse_args()
    run_dir = Path(args.run_dir).resolve()
    try:
        workset = build(run_dir, args.allow_legacy_meta, raw_union=args.raw_union,
                        jev_advisory_threshold=args.jev_advisory_threshold)
    except Exception as exc:
        atomic_json(run_dir / "integration-error.json",
                    {"stage": "builder", "error": f"{exc.__class__.__name__}: {exc}"})
        raise SystemExit(f"build-integration-workset: {exc}") from exc
    output = Path(args.output).resolve() if args.output else run_dir / "integration-workset.json"
    atomic_json(output, workset)
    if output.parent == run_dir:
        append_progress(run_dir, "workset-built")
    print(f"{output} candidates={len(workset['candidates'])} tokens~{workset['metrics']['tokens_estimate']}")


if __name__ == "__main__":
    main()
