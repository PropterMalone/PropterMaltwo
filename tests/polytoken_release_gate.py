#!/usr/bin/env python3
"""Mandatory machine-local freshness gate for Polytoken admission evidence.

This binds current local inputs and semantic traces; it is not cryptographic
attestation against an actor who controls the evidence, binary, and filesystem.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
ADMISSION_PATH = ROOT / "scripts/polytoken_admission.py"
ADMISSION_SPEC = importlib.util.spec_from_file_location("proptermaltwo_polytoken_admission", ADMISSION_PATH)
if ADMISSION_SPEC is None or ADMISSION_SPEC.loader is None:  # pragma: no cover - repository invariant
    raise RuntimeError(f"cannot load admission verifier from {ADMISSION_PATH}")
ADMISSION = importlib.util.module_from_spec(ADMISSION_SPEC)
ADMISSION_SPEC.loader.exec_module(ADMISSION)

SCHEMA_VERSION = 1
MAX_AGE = timedelta(hours=24)
MAX_FUTURE_SKEW = timedelta(minutes=5)
REQUIRED_RUNTIME_CHECKS = (
    "skill_discovery",
    "global_hook_load_reload",
    "benign_shell_exec_proceeds",
    "fixture_push_shaped_shell_exec_denied_before_side_effects",
    "unrelated_non_shell_tool_proceeds_without_hooks",
)
TOP_LEVEL_KEYS = {
    "schema_version",
    "started_at",
    "ended_at",
    "machine_binding_sha256",
    "polytoken_version",
    "admission_script",
    "polytoken_binary",
    "installed_config",
    "guard_inputs",
    "validators",
    "runtime_checks",
}
BOUND_FILE_KEYS = {"path", "sha256"}
GUARD_INPUT_KEYS = {"hook_template", "bridge", "push_guard", "commit_guard"}
VALIDATOR_KEYS = {"path", "sha256", "result", "subprocess"}
RESULT_KEYS = {"result", "subprocess", "supporting_subprocesses", "observation"}
SUBPROCESS_KEYS = {"argv", "returncode", "stdout", "stderr"}


class GateError(ValueError):
    """A safe, user-actionable gate rejection."""


def canonical(path: Path) -> str:
    return str(path.expanduser().resolve(strict=False))


def sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise GateError(f"cannot read bound input {path}: {exc.strerror or exc}") from exc


def machine_binding(machine_id_path: Path) -> str:
    """Hash raw bytes. Callers must never render the returned binding."""
    return sha256_file(machine_id_path)


def parse_utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise GateError(f"{field} must be a UTC timestamp string")
    if not value.endswith("Z"):
        raise GateError(f"{field} must use UTC Z notation")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise GateError(f"{field} is not a valid UTC timestamp") from exc
    if parsed.tzinfo != timezone.utc:
        raise GateError(f"{field} must be UTC")
    return parsed


def exact_object(value: Any, keys: set[str], field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GateError(f"{field} must be an object")
    actual = set(value)
    if actual != keys:
        missing = sorted(keys - actual)
        extra = sorted(actual - keys)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unknown " + ", ".join(extra))
        raise GateError(f"{field} has invalid fields ({'; '.join(details)})")
    return value


def validate_subprocess(value: Any, field: str) -> None:
    item = exact_object(value, SUBPROCESS_KEYS, field)
    if not isinstance(item["argv"], list) or not item["argv"] or not all(isinstance(arg, str) for arg in item["argv"]):
        raise GateError(f"{field}.argv must be a nonempty string array")
    if not isinstance(item["returncode"], int) or isinstance(item["returncode"], bool):
        raise GateError(f"{field}.returncode must be an integer")
    if not isinstance(item["stdout"], str) or not isinstance(item["stderr"], str):
        raise GateError(f"{field} stdout/stderr must be strings")


def validate_bound_file(value: Any, expected_path: Path, field: str) -> None:
    item = exact_object(value, BOUND_FILE_KEYS, field)
    if item["path"] != canonical(expected_path):
        raise GateError(f"{field} path is not the current configured path")
    digest = item["sha256"]
    if not isinstance(digest, str) or len(digest) != 64:
        raise GateError(f"{field} checksum is malformed")
    if digest != sha256_file(expected_path):
        raise GateError(f"{field} checksum is stale")


def exact_argv(record: dict[str, Any], expected: Sequence[str], field: str) -> None:
    if record["argv"] != list(expected):
        raise GateError(f"{field}.argv does not match the exact release admission command")


def runtime_invocation(record: dict[str, Any], binary: Path, prompt: str, field: str) -> Path:
    argv = record["argv"]
    prefix = [str(binary), "--working-dir"]
    suffix = ["exec", "--print-session-logs", "--max-tool-turns", "8"]
    if len(argv) not in (len(prefix) + 1 + len(suffix) + 1, len(prefix) + 1 + len(suffix) + 3):
        raise GateError(f"{field}.argv is not an exact Polytoken exec probe")
    if argv[:2] != prefix:
        raise GateError(f"{field}.argv does not bind the configured Polytoken executable and working directory")
    working_dir = Path(argv[2]).expanduser().resolve(strict=False)
    if argv[3:7] != suffix:
        raise GateError(f"{field}.argv lacks the exact exec/session-log/max-turn flags")
    tail = argv[7:]
    if tail == [prompt]:
        return working_dir
    if len(tail) == 3 and tail[0] == "--model" and tail[1] and tail[2] == prompt:
        return working_dir
    raise GateError(f"{field}.argv has an unexpected model option or prompt")


def current_polytoken_version(binary: Path) -> str:
    try:
        result = subprocess.run(
            [str(binary), "--version"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GateError(f"cannot determine current Polytoken version: {exc}") from exc
    if result.returncode != 0:
        raise GateError("cannot determine current Polytoken version; run polytoken --version and repair the installation")
    version = result.stdout.strip()
    if not version or "\n" in version:
        raise GateError("current Polytoken version output is malformed")
    return version


def validate_evidence(
    evidence: Any,
    *,
    evidence_path: Path,
    config_path: Path,
    hook_template_path: Path,
    bridge_path: Path,
    push_guard_path: Path,
    commit_guard_path: Path,
    skill_paths: Sequence[Path],
    machine_id_path: Path,
    polytoken_binary: Path,
    now: datetime,
) -> None:
    root = exact_object(evidence, TOP_LEVEL_KEYS, "evidence")
    if root["schema_version"] != SCHEMA_VERSION:
        raise GateError(f"evidence schema_version must be {SCHEMA_VERSION}")

    started = parse_utc(root["started_at"], "started_at")
    ended = parse_utc(root["ended_at"], "ended_at")
    if ended < started:
        raise GateError("ended_at is before started_at")
    if started > now + MAX_FUTURE_SKEW or ended > now + MAX_FUTURE_SKEW:
        raise GateError("evidence is future-dated by more than 5 minutes")
    if now - ended > MAX_AGE:
        raise GateError("evidence is older than 24 hours")

    binding = root["machine_binding_sha256"]
    if not isinstance(binding, str) or len(binding) != 64:
        raise GateError("machine binding is malformed")
    if binding != machine_binding(machine_id_path):
        raise GateError("evidence belongs to another machine")

    version = root["polytoken_version"]
    if not isinstance(version, str) or not version:
        raise GateError("polytoken_version must be a nonempty string")
    if version != current_polytoken_version(polytoken_binary):
        raise GateError("Polytoken version changed since admission")

    validate_bound_file(root["admission_script"], ADMISSION_PATH, "admission_script")
    validate_bound_file(root["polytoken_binary"], polytoken_binary, "polytoken_binary")
    validate_bound_file(root["installed_config"], config_path, "installed_config")
    guards = exact_object(root["guard_inputs"], GUARD_INPUT_KEYS, "guard_inputs")
    for name, path in (
        ("hook_template", hook_template_path),
        ("bridge", bridge_path),
        ("push_guard", push_guard_path),
        ("commit_guard", commit_guard_path),
    ):
        validate_bound_file(guards[name], path, f"guard_inputs.{name}")

    validators = root["validators"]
    if not isinstance(validators, list):
        raise GateError("validators must be an array")
    expected = [canonical(path) for path in skill_paths]
    if len(expected) != len(set(expected)):
        raise GateError("configured validator paths contain duplicates")
    seen: list[str] = []
    for index, raw in enumerate(validators):
        item = exact_object(raw, VALIDATOR_KEYS, f"validators[{index}]")
        if not isinstance(item["path"], str):
            raise GateError(f"validators[{index}].path must be a string")
        seen.append(item["path"])
        expected_skill = skill_paths[index] if index < len(skill_paths) else Path(item["path"])
        digest = item["sha256"]
        if not isinstance(digest, str) or len(digest) != 64 or digest != sha256_file(expected_skill):
            raise GateError(f"validators[{index}].sha256 is malformed or stale")
        if item["result"] != "pass":
            raise GateError(f"validator did not pass for {item['path']}")
        subprocess_record = item["subprocess"]
        validate_subprocess(subprocess_record, f"validators[{index}].subprocess")
        exact_argv(
            subprocess_record,
            [str(polytoken_binary), "validate", "skill", item["path"]],
            f"validators[{index}].subprocess",
        )
        if subprocess_record["returncode"] != 0:
            raise GateError(f"validator subprocess was nonzero for {item['path']}")
    if seen != expected:
        raise GateError("validator paths do not exactly match the current admitted skill paths in order")

    checks = exact_object(root["runtime_checks"], set(REQUIRED_RUNTIME_CHECKS), "runtime_checks")
    working_dirs: set[Path] = set()
    for name in REQUIRED_RUNTIME_CHECKS:
        item = exact_object(checks[name], RESULT_KEYS, f"runtime_checks.{name}")
        if item["result"] != "pass":
            raise GateError(f"runtime check {name} did not pass")
        if not isinstance(item["observation"], str) or not item["observation"]:
            raise GateError(f"runtime_checks.{name}.observation must be nonempty")
        record = item["subprocess"]
        validate_subprocess(record, f"runtime_checks.{name}.subprocess")
        if record["returncode"] != 0:
            raise GateError(f"runtime check {name} subprocess was nonzero")
        argv = record["argv"]
        if len(argv) < 8 or argv[:2] != [str(polytoken_binary), "--working-dir"]:
            raise GateError(f"runtime_checks.{name}.subprocess.argv is not an exact Polytoken exec probe")
        working_dir = Path(argv[2]).expanduser().resolve(strict=False)
        context, prompts = ADMISSION.probe_contract(working_dir)
        working_dirs.add(runtime_invocation(record, polytoken_binary, prompts[name], f"runtime_checks.{name}.subprocess"))
        actual_result, _ = ADMISSION.runtime_result(name, record, context)
        if actual_result != "pass":
            raise GateError(f"runtime check {name} raw session trace and sentinel observations do not independently pass")

        supporting = item["supporting_subprocesses"]
        if not isinstance(supporting, list):
            raise GateError(f"runtime_checks.{name}.supporting_subprocesses must be an array")
        expected_support_count = 2 if name == ADMISSION.RELOAD_PROBE else 0
        if len(supporting) != expected_support_count:
            raise GateError(f"runtime check {name} has an unexpected supporting subprocess set")
        for index, support_record in enumerate(supporting):
            validate_subprocess(support_record, f"runtime_checks.{name}.supporting_subprocesses[{index}]")
            if support_record["returncode"] != 0:
                raise GateError(f"runtime check {name} supporting subprocess {index} was nonzero")
        if name == ADMISSION.RELOAD_PROBE:
            exact_argv(supporting[0], [str(polytoken_binary), "--version"], f"runtime_checks.{name}.supporting_subprocesses[0]")
            if supporting[0]["stdout"].strip() != version:
                raise GateError("release evidence version record does not match polytoken_version")
            exact_argv(
                supporting[1],
                [str(polytoken_binary), "--working-dir", str(working_dir), "doctor", "--format", "json"],
                f"runtime_checks.{name}.supporting_subprocesses[1]",
            )
    if len(working_dirs) != 1:
        raise GateError("runtime probes do not share one exact isolated working directory")


def default_paths(args: argparse.Namespace) -> dict[str, Any]:
    home = Path(os.path.expanduser(os.environ.get("HOME", "~"))).resolve()
    xdg_config = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")).expanduser().resolve()
    xdg_data = Path(os.environ.get("XDG_DATA_HOME", home / ".local/share")).expanduser().resolve()
    polytoken_home = Path(os.environ.get("POLYTOKEN_HOME", xdg_config / "polytoken")).expanduser().resolve()
    proptermaltwo_home = Path(os.environ.get("PROPTERMALTWO_HOME", xdg_data / "proptermaltwo")).expanduser().resolve()
    repo = Path(__file__).resolve().parents[1]
    skills = [Path(path) for path in args.skill_path] if args.skill_path else [
        polytoken_home / "skills" / name / "SKILL.md" for name in ("code", "status", "kickoff", "wrap")
    ]
    return {
        "evidence_path": Path(args.evidence or proptermaltwo_home / "admission/polytoken-evidence-v1.json"),
        "config_path": Path(args.config or polytoken_home / "hooks.json"),
        "hook_template_path": Path(args.hook_template or repo / "adapters/polytoken/hooks.json.tmpl"),
        "bridge_path": Path(args.bridge or proptermaltwo_home / "shared/hooks/host-hook-bridge.py"),
        "push_guard_path": Path(args.push_guard or proptermaltwo_home / "shared/hooks/gh-identity-guard.py"),
        "commit_guard_path": Path(args.commit_guard or proptermaltwo_home / "shared/hooks/gh-commit-author-guard.py"),
        "skill_paths": skills,
        "machine_id_path": Path(args.machine_id or "/etc/machine-id"),
        "polytoken_binary": Path(args.polytoken_bin or "polytoken"),
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Block release unless fresh, local Polytoken admission evidence is current.")
    result.add_argument("--evidence")
    result.add_argument("--config")
    result.add_argument("--hook-template")
    result.add_argument("--bridge")
    result.add_argument("--push-guard")
    result.add_argument("--commit-guard")
    result.add_argument("--skill-path", action="append", default=[])
    result.add_argument("--machine-id", help=argparse.SUPPRESS)
    result.add_argument("--polytoken-bin")
    return result


def main(argv: Sequence[str] | None = None, *, now: datetime | None = None) -> int:
    args = parser().parse_args(argv)
    paths = default_paths(args)
    evidence_path = paths["evidence_path"]
    try:
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise GateError(f"admission evidence is absent at {evidence_path}") from exc
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise GateError(f"admission evidence is unreadable or malformed: {exc}") from exc
        validate_evidence(
            evidence,
            **paths,
            now=now or datetime.now(timezone.utc),
        )
    except GateError as exc:
        print(f"BLOCKED: {exc}")
        print("Remediation: rerun scripts/polytoken_admission.py in an explicit isolated home/config tree, then rerun this gate.")
        return 1
    print("PASS: fresh local Polytoken admission evidence matches all current release inputs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
