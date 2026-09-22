#!/usr/bin/env python3
"""Private calibration and paired-shadow evidence harness for ADR-22.

All label, score, and performance artifacts must live outside the public skill
repository. The acting NineAngel report is read-only throughout this workflow.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import statistics
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from integration_common import atomic_json, load_json
from jev_reconciliation import (MODEL, PROMPT_VERSION, prepare_run,
                                sha256_json, submitted_record,
                                validate_artifact)

D = Path(__file__).resolve().parent
SKILL_DIR = D.parent.resolve()
CALIBRATION_RUNS = 5
HOLDOUT_RUNS = 10
RUBRIC_VERSION = "ci-mechanism-v1"
SHADOW_DIRNAME = "jev-shadow-v1"


def load_script(name, filename):
    spec = importlib.util.spec_from_file_location(name, D / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load_script("jev_eval_builder", "build-integration-workset.py")
validator = load_script("jev_eval_validator", "validate-integration-decisions.py")


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value):
    if not isinstance(value, str):
        raise ValueError(f"invalid timestamp: {value!r}")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def private_path(value):
    path = Path(value).expanduser().resolve()
    if path == SKILL_DIR or SKILL_DIR in path.parents:
        raise ValueError("private Jev evaluation artifacts may not live in the skill repository")
    for parent in (path.parent, *path.parents):
        if (parent / ".git").exists():
            raise ValueError("private Jev evaluation artifacts may not live in a git repository")
    return path


def write_private(path, value, *, replace=False):
    path = private_path(path)
    if path.exists() and not replace:
        raise ValueError(f"refusing to replace private artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_json(path, value)
    path.chmod(0o600)
    return path


def pair_manifest(pairs):
    return [[pair["pair_id"], pair["left"]["raw_source_id"],
             pair["right"]["raw_source_id"]] for pair in pairs]


def calibration_entry(run_dir):
    run_dir = Path(run_dir).expanduser().resolve()
    if (run_dir / "jev-reconciliation.json").exists():
        raise ValueError(
            f"calibration must be registered before scoring: {run_dir}")
    _meta, eligibility, _rows, pairs, binding = prepare_run(run_dir)
    if not pairs:
        raise ValueError(f"calibration run has no cross-pass pairs: {run_dir}")
    return {
        "run_dir": str(run_dir),
        "binding_sha256": binding,
        "data_class": eligibility["data_class"],
        "pair_manifest_sha256": sha256_json(pair_manifest(pairs)),
        "pairs": [{
            "pair_id": pair["pair_id"],
            "persona": pair["persona"],
            "left": submitted_record(pair["left"]),
            "right": submitted_record(pair["right"]),
            "label": None,
        } for pair in pairs],
    }


def calibration_cohort_hash(entries):
    return sha256_json([{
        "run_dir": entry["run_dir"],
        "binding_sha256": entry["binding_sha256"],
        "pair_manifest_sha256": entry["pair_manifest_sha256"],
    } for entry in entries])


def prepare_calibration(run_dirs, output):
    if len(run_dirs) != CALIBRATION_RUNS:
        raise ValueError(f"calibration requires exactly {CALIBRATION_RUNS} runs")
    entries = [calibration_entry(path) for path in run_dirs]
    if len({entry["run_dir"] for entry in entries}) != len(entries):
        raise ValueError("calibration run paths must be unique")
    artifact = {
        "version": 1,
        "kind": "jev-reconciliation-calibration-labels",
        "created_at": now(),
        "model": MODEL,
        "prompt_version": PROMPT_VERSION,
        "label_enum": ["duplicate", "distinct", "ambiguous"],
        "instructions": (
            "Label every pair without opening jev-reconciliation.json: duplicate means the same "
            "underlying defect; distinct means separate defects; ambiguous means the text is "
            "insufficient. Do not add, remove, or reorder pairs."
        ),
        "runs": entries,
    }
    artifact["cohort_sha256"] = calibration_cohort_hash(entries)
    return write_private(output, artifact)


def validate_calibration_labels(labels):
    if (not isinstance(labels, dict) or labels.get("version") != 1 or
            labels.get("kind") != "jev-reconciliation-calibration-labels"):
        raise ValueError("unsupported calibration-label artifact")
    if labels.get("model") != MODEL or labels.get("prompt_version") != PROMPT_VERSION:
        raise ValueError("calibration labels target a different Jev model or prompt")
    runs = labels.get("runs")
    if not isinstance(runs, list) or len(runs) != CALIBRATION_RUNS:
        raise ValueError(f"calibration labels require exactly {CALIBRATION_RUNS} runs")
    if labels.get("cohort_sha256") != calibration_cohort_hash(runs):
        raise ValueError("calibration cohort binding changed")
    return runs


def freeze_threshold(labels_path, output):
    labels = load_json(private_path(labels_path))
    entries = validate_calibration_labels(labels)
    labeled_scores = []
    for entry in entries:
        run_dir = Path(entry["run_dir"]).resolve()
        _meta, _eligibility, _rows, pairs, binding = prepare_run(run_dir)
        if binding != entry.get("binding_sha256"):
            raise ValueError(f"calibration run changed after registration: {run_dir}")
        if sha256_json(pair_manifest(pairs)) != entry.get("pair_manifest_sha256"):
            raise ValueError(f"calibration pair universe changed: {run_dir}")
        artifact = load_json(run_dir / "jev-reconciliation.json")
        if parse_time(artifact.get("started_at")) < parse_time(labels["created_at"]):
            raise ValueError(f"Jev scores predate blind registration: {run_dir}")
        _expected, scored = validate_artifact(run_dir, artifact)
        label_rows = entry.get("pairs")
        if not isinstance(label_rows, list) or len(label_rows) != len(pairs):
            raise ValueError(f"calibration pair labels are incomplete: {run_dir}")
        for expected, row in zip(pairs, label_rows):
            if (not isinstance(row, dict) or row.get("pair_id") != expected["pair_id"] or
                    row.get("persona") != expected["persona"] or
                    row.get("left") != submitted_record(expected["left"]) or
                    row.get("right") != submitted_record(expected["right"])):
                raise ValueError(f"calibration pair identity changed: {run_dir}")
            label = row.get("label")
            if label not in ("duplicate", "distinct", "ambiguous"):
                raise ValueError(f"missing or invalid calibration label: {run_dir} {row.get('pair_id')}")
            labeled_scores.append((label, scored[row["pair_id"]]["score"]))

    duplicates = [score for label, score in labeled_scores if label == "duplicate"]
    distinct = [score for label, score in labeled_scores if label == "distinct"]
    if not duplicates or not distinct:
        raise ValueError("calibration needs at least one duplicate and one distinct label")
    threshold = math.nextafter(max(distinct), math.inf)
    recall = sum(score >= threshold for score in duplicates) / len(duplicates)
    passed = threshold <= 1 and recall >= 0.80
    result = {
        "version": 1,
        "kind": "jev-reconciliation-threshold",
        "created_at": now(),
        "model": MODEL,
        "prompt_version": PROMPT_VERSION,
        "cohort_sha256": labels["cohort_sha256"],
        "cohort_size": len(entries),
        "passed": passed,
        "attention_threshold": threshold if threshold <= 1 else None,
        "private_metrics": {
            "duplicate_count": len(duplicates),
            "distinct_count": len(distinct),
            "ambiguous_count": sum(label == "ambiguous" for label, _score in labeled_scores),
            "distinct_matches_at_threshold": (
                sum(score >= threshold for score in distinct) if threshold <= 1 else None),
            "duplicate_recall": recall if threshold <= 1 else None,
        },
    }
    return write_private(output, result)


def load_threshold(path):
    path = private_path(path)
    value = load_json(path)
    if (not isinstance(value, dict) or value.get("version") != 1 or
            value.get("kind") != "jev-reconciliation-threshold"):
        raise ValueError("unsupported Jev threshold artifact")
    if value.get("model") != MODEL or value.get("prompt_version") != PROMPT_VERSION:
        raise ValueError("threshold targets a different Jev model or prompt")
    threshold = value.get("attention_threshold")
    if (value.get("passed") is not True or not isinstance(threshold, (int, float)) or
            isinstance(threshold, bool) or threshold < 0 or threshold > 1):
        raise ValueError("calibration did not produce an acting attention threshold")
    return path, value


def begin_holdout(threshold_path, ledger_path):
    _path, threshold = load_threshold(threshold_path)
    ledger = {
        "version": 1,
        "kind": "jev-reconciliation-holdout",
        "created_at": now(),
        "model": MODEL,
        "prompt_version": PROMPT_VERSION,
        "threshold_sha256": sha256_json(threshold),
        "calibration_cohort_sha256": threshold["cohort_sha256"],
        "target_runs": HOLDOUT_RUNS,
        "rubric_version": RUBRIC_VERSION,
        "runs": [],
    }
    return write_private(ledger_path, ledger)


def load_ledger(path, threshold=None):
    path = private_path(path)
    ledger = load_json(path)
    if (not isinstance(ledger, dict) or ledger.get("version") != 1 or
            ledger.get("kind") != "jev-reconciliation-holdout" or
            ledger.get("target_runs") != HOLDOUT_RUNS or
            ledger.get("rubric_version") != RUBRIC_VERSION):
        raise ValueError("unsupported holdout ledger")
    if ledger.get("model") != MODEL or ledger.get("prompt_version") != PROMPT_VERSION:
        raise ValueError("holdout targets a different Jev model or prompt")
    if threshold is not None and ledger.get("threshold_sha256") != sha256_json(threshold):
        raise ValueError("holdout ledger is bound to a different threshold")
    if not isinstance(ledger.get("runs"), list):
        raise ValueError("holdout ledger runs must be an array")
    return path, ledger


def validate_decisions(workset, decisions):
    errors = validator.validate(workset, decisions, SKILL_DIR / "schemas")
    if errors:
        raise ValueError("invalid integration decisions: " + "; ".join(errors))


def run_shadow(run_dir, threshold_path, ledger_path, dispatch=None):
    threshold_path, threshold = load_threshold(threshold_path)
    ledger_path, ledger = load_ledger(ledger_path, threshold)
    run_dir = Path(run_dir).expanduser().resolve()
    if len(ledger["runs"]) >= HOLDOUT_RUNS:
        raise ValueError("holdout cohort is already full")
    if any(row.get("run_dir") == str(run_dir) for row in ledger["runs"]):
        raise ValueError(f"run is already registered in the holdout: {run_dir}")
    shadow_dir = run_dir / SHADOW_DIRNAME
    if shadow_dir.exists():
        raise ValueError(f"shadow directory already exists: {shadow_dir}")

    baseline_workset = load_json(run_dir / "integration-workset.json")
    baseline_decisions = load_json(run_dir / "integration-decisions.json")
    validate_decisions(baseline_workset, baseline_decisions)
    if baseline_decisions.get("producer") != "reducer":
        raise ValueError("holdout requires a non-degraded Sonnet/reducer baseline")
    artifact = load_json(run_dir / "jev-reconciliation.json")
    _pairs, _scored = validate_artifact(run_dir, artifact)
    artifact_started = parse_time(artifact.get("started_at"))
    if artifact_started < parse_time(threshold["created_at"]):
        raise ValueError("holdout Jev artifact predates the frozen threshold")
    if ledger["runs"] and artifact_started <= parse_time(ledger["runs"][-1]["score_started_at"]):
        raise ValueError("holdout runs must be registered in score chronology")

    entry = {
        "run_dir": str(run_dir),
        "binding_sha256": artifact["binding_sha256"],
        "score_started_at": artifact["started_at"],
        "registered_at": now(),
        "status": "registered",
        "shadow_dir": str(shadow_dir),
    }
    ledger["runs"].append(entry)
    write_private(ledger_path, ledger, replace=True)

    try:
        shadow_dir.mkdir(mode=0o700)
        workset = builder.build(
            run_dir, raw_union=True,
            jev_advisory_threshold=threshold["attention_threshold"])
        workset["run"]["shadow_source_run"] = str(run_dir)
        workset["run"]["run_dir"] = str(shadow_dir)
        write_private(shadow_dir / "integration-workset.json", workset)
        (shadow_dir / "usage.jsonl").write_text("", encoding="utf-8")
        (shadow_dir / "usage.jsonl").chmod(0o600)
        (shadow_dir / "PROGRESS").write_text(
            f"jev-shadow-registered {entry['registered_at']}\n", encoding="utf-8")

        command = [str(dispatch or D / "dispatch-integration.sh"), str(shadow_dir)]
        result = subprocess.run(command, text=True, capture_output=True, timeout=1800)
        if result.returncode:
            raise RuntimeError((result.stderr or result.stdout or
                                "shadow reducer failed").strip().splitlines()[-1])
        decisions = load_json(shadow_dir / "integration-decisions.json")
        validate_decisions(workset, decisions)
        if decisions.get("producer") != "reducer":
            raise RuntimeError(
                f"shadow reducer degraded: {decisions.get('degraded_reason') or 'unknown'}")
        telemetry = load_json(shadow_dir / "integration-telemetry.json")
        manifest = {
            "version": 1,
            "kind": "jev-reconciliation-shadow",
            "completed_at": now(),
            "source_run": str(run_dir),
            "threshold_sha256": sha256_json(threshold),
            "binding_sha256": artifact["binding_sha256"],
            "workset_sha256": sha256_json(workset),
            "decisions_sha256": sha256_json(decisions),
            "telemetry_sha256": sha256_json(telemetry),
        }
        write_private(shadow_dir / "jev-shadow-manifest.json", manifest)
        entry.update({"status": "complete", "completed_at": manifest["completed_at"],
                      "manifest_sha256": sha256_json(manifest)})
        write_private(ledger_path, ledger, replace=True)
        return shadow_dir
    except Exception as exc:
        entry.update({"status": "failed", "completed_at": now(),
                      "failure": f"{exc.__class__.__name__}: {exc}"})
        write_private(ledger_path, ledger, replace=True)
        raise


def decision_groups(workset, decisions):
    candidates = {row["id"]: row for row in workset["candidates"]}
    groups = []
    for finding in decisions["findings"]:
        source_rows = [candidates[cid] for cid in finding["source_candidate_ids"]]
        raw_ids = sorted({rid for row in source_rows for rid in row["raw_source_ids"]})
        evidence = []
        for row in source_rows:
            evidence.append({
                "candidate_id": row["id"],
                "persona": row.get("persona"),
                "severity": row.get("severity"),
                "title": row.get("title"),
                "file": row.get("file"),
                "line": row.get("line"),
                "description": row.get("description"),
                "raw_source_ids": row.get("raw_source_ids"),
            })
        groups.append({
            "decision_id": finding["decision_id"],
            "severity": finding["severity"],
            "title": finding["title"],
            "summary": finding["summary"],
            "raw_source_ids": raw_ids,
            "source_evidence": evidence,
        })
    return groups


def completed_holdout_runs(ledger):
    runs = ledger.get("runs") or []
    if len(runs) != HOLDOUT_RUNS:
        raise ValueError(f"holdout requires exactly {HOLDOUT_RUNS} registered runs")
    if any(row.get("status") != "complete" for row in runs):
        raise ValueError("every registered holdout run must complete before adjudication")
    return runs


def adjudication_artifact(ledger):
    presence, merges = [], []
    for run_index, row in enumerate(completed_holdout_runs(ledger), 1):
        run_dir = Path(row["run_dir"])
        shadow_dir = Path(row["shadow_dir"])
        baseline = decision_groups(load_json(run_dir / "integration-workset.json"),
                                   load_json(run_dir / "integration-decisions.json"))
        alternate = decision_groups(load_json(shadow_dir / "integration-workset.json"),
                                    load_json(shadow_dir / "integration-decisions.json"))
        material = [item for item in baseline
                    if item["severity"] in ("critical", "important")]
        for item in material:
            raw = set(item["raw_source_ids"])
            comparisons = [candidate for candidate in alternate
                           if raw & set(candidate["raw_source_ids"])]
            presence.append({
                "id": f"r{run_index:02d}-presence-{len(presence) + 1:04d}",
                "run_key": sha256_json(str(run_dir))[:12],
                "reference_finding": item,
                "comparison_findings": comparisons,
                "label": None,
                "label_enum": ["present", "absent", "ambiguous"],
            })
        for alternate_item in alternate:
            raw = set(alternate_item["raw_source_ids"])
            overlaps = [item for item in material if raw & set(item["raw_source_ids"])]
            if len(overlaps) < 2:
                continue
            merges.append({
                "id": f"r{run_index:02d}-merge-{len(merges) + 1:04d}",
                "run_key": sha256_json(str(run_dir))[:12],
                "comparison_finding": alternate_item,
                "reference_findings": overlaps,
                "label": None,
                "label_enum": ["same-mechanism", "distinct-mechanisms", "ambiguous"],
            })
    return {
        "version": 1,
        "kind": "jev-reconciliation-holdout-adjudication",
        "created_at": now(),
        "rubric_version": RUBRIC_VERSION,
        "ledger_sha256": sha256_json(ledger),
        "instructions": (
            "Adjudicate from the displayed text and raw-source lineage without opening Jev scores "
            "or performance telemetry. For every reference finding, mark whether its mechanism is "
            "present in the comparison findings. For every merge case, mark whether the reference "
            "findings are the same or distinct mechanisms."
        ),
        "presence": presence,
        "merges": merges,
    }


def prepare_adjudication(ledger_path, output):
    _path, ledger = load_ledger(ledger_path)
    return write_private(output, adjudication_artifact(ledger))


def usage_tokens(value):
    if not isinstance(value, dict):
        return None
    if isinstance(value.get("total_tokens"), int):
        return value["total_tokens"]
    inp, out = value.get("input_tokens"), value.get("output_tokens")
    return inp + out if isinstance(inp, int) and isinstance(out, int) else None


def read_usage_rows(path):
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def integration_window_ms(rows):
    starts, ends = [], []
    for row in rows:
        if row.get("phase") not in ("reconciler", "integrator"):
            continue
        end = parse_time(row["ended_at"]) if row.get("ended_at") else None
        start = parse_time(row["started_at"]) if row.get("started_at") else None
        if start is None and end is not None and isinstance(row.get("duration_ms"), int):
            start = datetime.fromtimestamp(
                end.timestamp() - row["duration_ms"] / 1000, tz=timezone.utc)
        if start:
            starts.append(start)
        if end:
            ends.append(end)
    if not starts or not ends:
        return None
    return round((max(ends) - min(starts)).total_seconds() * 1000)


def run_metrics(row):
    run_dir, shadow_dir = Path(row["run_dir"]), Path(row["shadow_dir"])
    artifact = load_json(run_dir / "jev-reconciliation.json")
    baseline_telemetry = load_json(run_dir / "integration-telemetry.json")
    shadow_telemetry = load_json(shadow_dir / "integration-telemetry.json")
    baseline_rows = read_usage_rows(run_dir / "usage.jsonl")
    reconciler_tokens = [item.get("total_tokens") for item in baseline_rows
                         if item.get("phase") == "reconciler"]
    if any(not isinstance(value, int) for value in reconciler_tokens):
        raise ValueError(f"baseline reconciler token usage is incomplete: {run_dir}")
    baseline_stage2 = usage_tokens(baseline_telemetry)
    jev_tokens = [usage_tokens(batch.get("usage")) for batch in artifact.get("batches", [])]
    shadow_stage2 = usage_tokens(shadow_telemetry)
    if (baseline_stage2 is None or shadow_stage2 is None or
            any(value is None for value in jev_tokens)):
        raise ValueError(f"reported model-token usage is incomplete: {run_dir}")
    baseline_wall = integration_window_ms(baseline_rows)
    if baseline_wall is None or not isinstance(artifact.get("elapsed_ms"), int):
        raise ValueError(f"wall-time evidence is incomplete: {run_dir}")
    shadow_duration = shadow_telemetry.get("duration_ms")
    if not isinstance(shadow_duration, int):
        raise ValueError(f"shadow wall-time evidence is incomplete: {run_dir}")
    shadow_wall = artifact["elapsed_ms"] + shadow_duration
    baseline_shards = baseline_telemetry.get("shards", 1)
    shadow_shards = shadow_telemetry.get("shards", 1)
    if not isinstance(baseline_shards, int) or not isinstance(shadow_shards, int):
        raise ValueError(f"shard evidence is incomplete: {run_dir}")
    return {
        "run_key": sha256_json(str(run_dir.resolve()))[:12],
        "baseline_tokens": sum(reconciler_tokens) + baseline_stage2,
        "shadow_tokens": sum(jev_tokens) + shadow_stage2,
        "baseline_wall_ms": baseline_wall,
        "shadow_wall_ms": shadow_wall,
        "baseline_shards": baseline_shards,
        "shadow_shards": shadow_shards,
    }


def compare_adjudication(expected, actual):
    if (actual.get("version") != 1 or
            actual.get("kind") != "jev-reconciliation-holdout-adjudication" or
            actual.get("rubric_version") != RUBRIC_VERSION or
            actual.get("ledger_sha256") != expected["ledger_sha256"]):
        raise ValueError("adjudication artifact is not bound to this holdout")
    for key in ("presence", "merges"):
        wanted = expected[key]
        got = actual.get(key)
        if not isinstance(got, list) or len(got) != len(wanted):
            raise ValueError(f"adjudication {key} rows changed")
        for left, right in zip(wanted, got):
            left_core = {k: v for k, v in left.items() if k != "label"}
            right_core = {k: v for k, v in right.items() if k != "label"}
            if left_core != right_core:
                raise ValueError(f"adjudication row changed: {left.get('id')}")


def evaluate_holdout(ledger_path, adjudication_path, output):
    _path, ledger = load_ledger(ledger_path)
    expected = adjudication_artifact(ledger)
    actual = load_json(private_path(adjudication_path))
    compare_adjudication(expected, actual)
    presence_labels = [row.get("label") for row in actual["presence"]]
    merge_labels = [row.get("label") for row in actual["merges"]]
    if any(label not in ("present", "absent", "ambiguous") for label in presence_labels):
        raise ValueError("presence adjudication is incomplete")
    if any(label not in ("same-mechanism", "distinct-mechanisms", "ambiguous")
           for label in merge_labels):
        raise ValueError("merge adjudication is incomplete")
    metrics = [run_metrics(row) for row in completed_holdout_runs(ledger)]
    median_baseline_tokens = statistics.median(row["baseline_tokens"] for row in metrics)
    median_shadow_tokens = statistics.median(row["shadow_tokens"] for row in metrics)
    median_baseline_wall = statistics.median(row["baseline_wall_ms"] for row in metrics)
    median_shadow_wall = statistics.median(row["shadow_wall_ms"] for row in metrics)
    shard_deltas = [row["shadow_shards"] - row["baseline_shards"] for row in metrics]
    clauses = {
        "no_missing_ci_mechanism": (presence_labels.count("absent") == 0 and
                                    presence_labels.count("ambiguous") == 0),
        "no_distinct_ci_false_merge": (merge_labels.count("distinct-mechanisms") == 0 and
                                        merge_labels.count("ambiguous") == 0),
        "shard_growth_bounded": (sum(delta > 0 for delta in shard_deltas) <= 2 and
                                 max(shard_deltas, default=0) <= 1),
        "median_tokens_at_most_75pct": (
            median_shadow_tokens <= 0.75 * median_baseline_tokens),
        "median_wall_at_most_125pct": (
            median_shadow_wall <= 1.25 * median_baseline_wall),
    }
    result = {
        "version": 1,
        "kind": "jev-reconciliation-holdout-result",
        "created_at": now(),
        "model": MODEL,
        "prompt_version": PROMPT_VERSION,
        "cohort_size": len(metrics),
        "passed": all(clauses.values()),
        "clauses": clauses,
        "private_metrics": {
            "missing_ci_mechanisms": presence_labels.count("absent"),
            "ambiguous_presence": presence_labels.count("ambiguous"),
            "distinct_ci_false_merges": merge_labels.count("distinct-mechanisms"),
            "ambiguous_merges": merge_labels.count("ambiguous"),
            "runs_with_extra_shard": sum(delta > 0 for delta in shard_deltas),
            "max_shard_delta": max(shard_deltas, default=0),
            "median_baseline_tokens": median_baseline_tokens,
            "median_shadow_tokens": median_shadow_tokens,
            "median_baseline_wall_ms": median_baseline_wall,
            "median_shadow_wall_ms": median_shadow_wall,
            "runs": metrics,
        },
    }
    return write_private(output, result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare-calibration")
    prepare.add_argument("--output", required=True)
    prepare.add_argument("run_dirs", nargs="+")

    freeze = sub.add_parser("freeze-threshold")
    freeze.add_argument("--labels", required=True)
    freeze.add_argument("--output", required=True)

    begin = sub.add_parser("begin-holdout")
    begin.add_argument("--threshold", required=True)
    begin.add_argument("--ledger", required=True)

    shadow = sub.add_parser("run-shadow")
    shadow.add_argument("run_dir")
    shadow.add_argument("--threshold", required=True)
    shadow.add_argument("--ledger", required=True)

    adjudicate = sub.add_parser("prepare-adjudication")
    adjudicate.add_argument("--ledger", required=True)
    adjudicate.add_argument("--output", required=True)

    evaluate = sub.add_parser("evaluate-holdout")
    evaluate.add_argument("--ledger", required=True)
    evaluate.add_argument("--adjudication", required=True)
    evaluate.add_argument("--output", required=True)

    args = parser.parse_args()
    try:
        if args.command == "prepare-calibration":
            path = prepare_calibration(args.run_dirs, args.output)
        elif args.command == "freeze-threshold":
            path = freeze_threshold(args.labels, args.output)
        elif args.command == "begin-holdout":
            path = begin_holdout(args.threshold, args.ledger)
        elif args.command == "run-shadow":
            path = run_shadow(args.run_dir, args.threshold, args.ledger)
        elif args.command == "prepare-adjudication":
            path = prepare_adjudication(args.ledger, args.output)
        else:
            path = evaluate_holdout(args.ledger, args.adjudication, args.output)
        print(path)
    except Exception as exc:
        raise SystemExit(f"jev-reconciliation-eval: {exc}") from exc


if __name__ == "__main__":
    main()
