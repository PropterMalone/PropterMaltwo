#!/usr/bin/env python3
"""Atomically complete ADR-20 run-meta.json before integration.

Usage:
  record-run-meta.py RUN_DIR --mode diff|full --reader-mode on|off
      --files-reviewed N --preflight-json JSON --personas-run a,b
      [--personas-dropped-json JSON] [--personas-failed-json JSON]
      [--codebase-files N] [--codebase-lines N] [--multiball N]
      [--pass-denominators-json JSON] [--previous-run-dir DIR]
      [--jev-data-class ineligible|public|synthetic|private-approved]
      [--jev-identifiers-stripped] [--jev-approval-basis TEXT]
"""
import argparse
import json
import os
import tempfile
from pathlib import Path

from integration_common import normalize_named_reasons


def json_value(raw, expected, label):
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{label}: invalid JSON: {exc}") from exc
    if not isinstance(value, expected):
        raise SystemExit(f"{label}: expected {expected.__name__}")
    return value


def atomic_json(path, value):
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--mode", required=True, choices=("diff", "full"))
    ap.add_argument("--reader-mode", required=True, choices=("on", "off"))
    ap.add_argument("--files-reviewed", required=True, type=int)
    ap.add_argument("--preflight-json", required=True)
    ap.add_argument("--personas-run", required=True)
    ap.add_argument("--personas-dropped-json", default="[]")
    ap.add_argument("--personas-failed-json", default="[]")
    ap.add_argument("--codebase-files", type=int)
    ap.add_argument("--codebase-lines", type=int)
    ap.add_argument("--multiball", type=int)
    ap.add_argument("--pass-denominators-json", default="{}")
    ap.add_argument("--previous-run-dir")
    ap.add_argument("--jev-data-class", default="ineligible",
                    choices=("ineligible", "public", "synthetic", "private-approved"))
    ap.add_argument("--jev-identifiers-stripped", action="store_true")
    ap.add_argument("--jev-approval-basis")
    args = ap.parse_args()

    run_dir = Path(args.run_dir).resolve()
    path = run_dir / "run-meta.json"
    if not path.is_file():
        raise SystemExit(f"missing run-meta.json (create the run with init-run.sh): {path}")
    meta = json.loads(path.read_text(encoding="utf-8"))
    if meta.get("integration_pipeline") != "semantic-reducer-v1":
        raise SystemExit("run-meta.json is not a semantic-reducer-v1 run")
    personas = [p.strip() for p in args.personas_run.split(",") if p.strip()]
    if not personas:
        raise SystemExit("--personas-run must name at least one persona")
    if args.files_reviewed < 0:
        raise SystemExit("--files-reviewed must be non-negative")
    if args.multiball is not None and args.multiball < 2:
        raise SystemExit("--multiball must be >=2 when supplied")
    if args.jev_data_class == "public" and not args.jev_identifiers_stripped:
        raise SystemExit("public Jev data requires --jev-identifiers-stripped")
    if (args.jev_data_class == "private-approved" and
            (not args.jev_approval_basis or len(args.jev_approval_basis.strip()) < 8)):
        raise SystemExit("private-approved Jev data requires a specific --jev-approval-basis")

    denominators = json_value(args.pass_denominators_json, dict, "--pass-denominators-json")
    if args.multiball:
        for persona in personas:
            denominators.setdefault(persona, args.multiball)
    if any(not isinstance(v, int) or v < 1 for v in denominators.values()):
        raise SystemExit("pass denominators must be positive integers")

    try:
        dropped = normalize_named_reasons(
            json_value(args.personas_dropped_json, list, "--personas-dropped-json"),
            "--personas-dropped-json entry",
        )
        failed = normalize_named_reasons(
            json_value(args.personas_failed_json, list, "--personas-failed-json"),
            "--personas-failed-json entry",
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    meta.update({
        "status": "ready",
        "mode": args.mode,
        "reader_mode": args.reader_mode,
        "files_reviewed": args.files_reviewed,
        "preflight": json_value(args.preflight_json, dict, "--preflight-json"),
        "multiball": args.multiball,
        "pass_denominators": denominators,
        "personas_run": personas,
        "personas_dropped": dropped,
        "personas_failed": failed,
        "codebase": {"files": args.codebase_files, "lines": args.codebase_lines},
        "previous_run_dir": (str(Path(args.previous_run_dir).resolve())
                             if args.previous_run_dir else None),
        "jev_eligibility": {
            "data_class": args.jev_data_class,
            "identifiers_stripped": args.jev_identifiers_stripped,
            "approval_basis": args.jev_approval_basis,
        },
    })
    atomic_json(path, meta)
    print(path)


if __name__ == "__main__":
    main()
