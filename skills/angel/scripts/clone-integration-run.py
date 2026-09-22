#!/usr/bin/env python3
"""Create a fresh reducer-era run from an immutable reviewed workset.

The clone carries only pre-integration evidence and usage. Verification,
dispositions, rendered output, reducer attempts, and integration usage stay with
the original run.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import uuid
from pathlib import Path

from integration_common import atomic_json, atomic_text, estimate_tokens, load_json


PRE_INTEGRATION_PHASES = {"reader", "persona", "reconciler"}


def clone(source: Path, runs_root: Path) -> Path:
    source = source.resolve()
    required = ("run-meta.json", "integration-workset.json", "PROJECT_COMMIT")
    missing = [name for name in required if not (source / name).is_file()]
    if missing:
        raise ValueError("source run is missing: " + ", ".join(missing))
    meta = load_json(source / "run-meta.json")
    workset = load_json(source / "integration-workset.json")
    if (meta.get("integration_pipeline") != "semantic-reducer-v1"
            or meta.get("status") != "ready"):
        raise ValueError("source is not a ready semantic-reducer-v1 run")

    runs_root.mkdir(parents=True, exist_ok=True)
    while True:
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = runs_root / f"{stamp}-{uuid.uuid4().hex[:8]}"
        try:
            target.mkdir(mode=0o700)
            break
        except FileExistsError:
            continue

    try:
        for dirname in ("findings", "passes", "reconciled"):
            src = source / dirname
            if src.is_dir():
                shutil.copytree(src, target / dirname)
        for filename in ("PROJECT_COMMIT", "EXPERIMENT"):
            src = source / filename
            if src.is_file():
                shutil.copy2(src, target / filename)

        usage_rows = []
        usage_path = source / "usage.jsonl"
        if usage_path.is_file():
            for line in usage_path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("phase") in PRE_INTEGRATION_PHASES:
                    usage_rows.append(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
        atomic_text(target / "usage.jsonl", "\n".join(usage_rows) + ("\n" if usage_rows else ""))

        meta["run_dir"] = str(target)
        meta["previous_run_dir"] = str(source)
        atomic_json(target / "run-meta.json", meta)

        workset["run"]["run_dir"] = str(target)
        byte_count, tokens = estimate_tokens({k: v for k, v in workset.items() if k != "metrics"})
        workset["metrics"]["utf8_bytes"] = byte_count
        workset["metrics"]["tokens_estimate"] = tokens
        atomic_json(target / "integration-workset.json", workset)
        atomic_text(target / "PROGRESS", f"clone-created-from {source}\n")
        return target
    except Exception:
        shutil.rmtree(target)
        raise


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source_run")
    ap.add_argument("--runs-root")
    args = ap.parse_args()
    source = Path(args.source_run)
    root = Path(args.runs_root or os.environ.get("ANGEL_RUNS_ROOT") or source.resolve().parent)
    try:
        print(clone(source, root))
    except Exception as exc:
        raise SystemExit(f"clone-integration-run: {exc}") from exc


if __name__ == "__main__":
    main()
