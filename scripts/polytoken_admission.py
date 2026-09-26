#!/usr/bin/env python3
"""Generate schema-v1 evidence from real, isolated Polytoken runtime traces.

The runner is read-only with respect to configuration. It invokes validators,
doctor, and five `polytoken exec --print-session-logs` probes, preserving every
subprocess stream. Runtime passes come only from parsed trace events and direct
filesystem observations, never from the model's final prose.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Sequence

SCHEMA_VERSION = 1
PUSH_HOOK = "proptermaltwo-gh-push-identity"
COMMIT_HOOK = "proptermaltwo-gh-commit-author"
SKILL_PROBE = "skill_discovery"
RELOAD_PROBE = "global_hook_load_reload"
BENIGN_PROBE = "benign_shell_exec_proceeds"
PUSH_PROBE = "fixture_push_shaped_shell_exec_denied_before_side_effects"
NON_SHELL_PROBE = "unrelated_non_shell_tool_proceeds_without_hooks"
RUNTIME_PROBES = (SKILL_PROBE, RELOAD_PROBE, BENIGN_PROBE, PUSH_PROBE, NON_SHELL_PROBE)
ADMITTED_SKILLS = ("code", "status", "kickoff", "wrap")


class AdmissionError(ValueError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical(path: Path) -> str:
    return str(path.expanduser().resolve(strict=False))


def digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise AdmissionError(f"cannot read required input {path}: {exc.strerror or exc}") from exc


def bound_file(path: Path) -> dict[str, str]:
    return {"path": canonical(path), "sha256": digest(path)}


def run(command: Sequence[str], env: dict[str, str], cwd: Path, timeout: int) -> dict[str, Any]:
    try:
        result = subprocess.run(
            list(command), cwd=cwd, env=env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, check=False,
        )
        return {"argv": list(command), "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return {"argv": list(command), "returncode": 124, "stdout": stdout, "stderr": stderr + f"\ntimeout after {timeout}s\n"}
    except OSError as exc:
        return {"argv": list(command), "returncode": 127, "stdout": "", "stderr": str(exc)}


def json_events(raw: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def event_name(event: dict[str, Any]) -> str | None:
    if isinstance(event.get("type"), str):
        return event["type"]
    fields = event.get("fields")
    return fields.get("event") if isinstance(fields, dict) and isinstance(fields.get("event"), str) else None


def event_fields(event: dict[str, Any]) -> dict[str, Any]:
    fields = event.get("fields")
    return fields if isinstance(fields, dict) else event


def tool_calls(events: Sequence[dict[str, Any]], tool_name: str) -> list[dict[str, Any]]:
    return [event for event in events if event_name(event) == "tool_call" and event.get("name") == tool_name]


def has_lifecycle(events: Sequence[dict[str, Any]], event_type: str, tool_name: str, call_id: str) -> bool:
    return any(
        event_name(event) == event_type
        and event_fields(event).get("tool_name") == tool_name
        and event_fields(event).get("call_id") == call_id
        for event in events
    )


def hooks_for_call(events: Sequence[dict[str, Any]], call: dict[str, Any]) -> list[dict[str, Any]]:
    call_id = call.get("call_id")
    # hook_fired lacks call_id in 0.8.14. Bound it to the interval between the
    # exact tool_call and its result/next tool_call; probes demand one target call.
    start = events.index(call)
    result: list[dict[str, Any]] = []
    for event in events[start + 1:]:
        if event_name(event) == "tool_call":
            break
        if event_name(event) == "hook_fired" and event.get("event_type") == "pre_tool_use":
            result.append(event)
        if event_name(event) == "tool_result" and event.get("call_id") == call_id:
            break
    return result


def runtime_result(name: str, record: dict[str, Any], context: dict[str, Any]) -> tuple[str, str]:
    events = json_events(record["stderr"])
    if record["returncode"] != 0 or not events:
        return "fail", "exec failed or emitted no parseable session trace"

    if name == SKILL_PROBE:
        calls = tool_calls(events, "skill")
        expected = tuple(context["skill_names"])
        passed = len(calls) == len(expected)
        for skill_name in expected:
            matching = [call for call in calls if call.get("input", {}).get("name") == skill_name]
            passed = passed and len(matching) == 1
            if len(matching) == 1:
                call_id = matching[0].get("call_id")
                passed = passed and isinstance(call_id, str) and has_lifecycle(events, "tool_call.completed", "skill", call_id)
        return ("pass" if passed else "fail", "trace contains exactly one completed native skill call for every admitted skill")

    if name == RELOAD_PROBE:
        calls = tool_calls(events, "shell_exec")
        exact = [call for call in calls if call.get("input", {}).get("command") == context["reload_command"]]
        passed = len(calls) == 1 and len(exact) == 1
        if len(exact) == 1:
            call_id = exact[0].get("call_id")
            fired = hooks_for_call(events, exact[0])
            identity_hooks = [event for event in fired if event.get("hook_name") in {PUSH_HOOK, COMMIT_HOOK}]
            passed = (
                passed
                and isinstance(call_id, str)
                and has_lifecycle(events, "tool_call.completed", "shell_exec", call_id)
                and sorted((event.get("hook_name"), event.get("outcome")) for event in identity_hooks)
                == sorted(((PUSH_HOOK, "allowed"), (COMMIT_HOOK, "allowed")))
            )
        return ("pass" if passed else "fail", "trace contains the exact reload sentinel and both installed global hooks allowed its call")

    if name == BENIGN_PROBE:
        calls = tool_calls(events, "shell_exec")
        exact = [call for call in calls if call.get("input", {}).get("command") == context["benign_command"]]
        passed = len(calls) == 1 and len(exact) == 1
        if len(exact) == 1:
            identity_hooks = [
                event for event in hooks_for_call(events, exact[0])
                if event.get("hook_name") in {PUSH_HOOK, COMMIT_HOOK}
            ]
            passed = (
                passed
                and isinstance(exact[0].get("call_id"), str)
                and has_lifecycle(events, "tool_call.completed", "shell_exec", exact[0]["call_id"])
                and sorted((event.get("hook_name"), event.get("outcome")) for event in identity_hooks)
                == sorted(((PUSH_HOOK, "allowed"), (COMMIT_HOOK, "allowed")))
                and context["benign_marker"].is_file()
            )
        return ("pass" if passed else "fail", "exact benign shell call completed and created its controlled sentinel")

    if name == PUSH_PROBE:
        calls = tool_calls(events, "shell_exec")
        exact = [call for call in calls if call.get("input", {}).get("command") == context["push_command"]]
        if len(calls) != 1 or len(exact) != 1 or not isinstance(exact[0].get("call_id"), str):
            return "fail", "trace lacks exactly one fixture push-shaped shell call with a call ID"
        call = exact[0]
        fired = hooks_for_call(events, call)
        denied = any(
            event_name(event) == "tool_call.denied"
            and event_fields(event).get("tool_name") == "shell_exec"
            and event_fields(event).get("call_id") == call.get("call_id")
            and event_fields(event).get("blocked_by_hook") == PUSH_HOOK
            for event in events
        )
        hook_blocked = any(event.get("hook_name") == PUSH_HOOK and event.get("outcome") == "blocked" for event in fired)
        passed = denied and hook_blocked and not context["push_marker"].exists() and not has_lifecycle(events, "tool_call.started", "shell_exec", call.get("call_id"))
        return ("pass" if passed else "fail", "push guard blocked the exact call before tool start and no side-effect sentinel exists")

    if name == NON_SHELL_PROBE:
        reads = tool_calls(events, "file_read")
        exact = [call for call in reads if call.get("input", {}).get("path") == canonical(context["non_shell_fixture"])]
        identity_hooks = [event for event in events if event_name(event) == "hook_fired" and event.get("hook_name") in {PUSH_HOOK, COMMIT_HOOK}]
        passed = (
            len(reads) == 1
            and not tool_calls(events, "shell_exec")
            and len(exact) == 1
            and isinstance(exact[0].get("call_id"), str)
            and has_lifecycle(events, "tool_call.completed", "file_read", exact[0]["call_id"])
            and not identity_hooks
        )
        return ("pass" if passed else "fail", "exact non-shell file_read completed and neither identity hook fired")

    raise AssertionError(name)


def probe_contract(working_dir: Path) -> tuple[dict[str, Any], dict[str, str]]:
    """Return the exact trace-validation context and prompts for an isolated work tree."""
    working_dir = working_dir.expanduser().resolve(strict=False)
    benign_marker = working_dir / ".proptermaltwo-benign-shell"
    push_marker = working_dir / ".proptermaltwo-push-side-effect"
    non_shell_fixture = working_dir / ".proptermaltwo-non-shell-fixture"
    benign_command = f"printf '%s\\n' benign > {json.dumps(str(benign_marker))}"
    nonexistent_remote = working_dir / ".proptermaltwo-nonexistent-remote"
    push_command = f"git push --dry-run {json.dumps(str(nonexistent_remote))}; printf '%s\\n' side-effect > {json.dumps(str(push_marker))}"
    reload_command = "printf '%s\\n' reload-probe"
    context = {
        "skill_names": ADMITTED_SKILLS,
        "reload_command": reload_command,
        "benign_command": benign_command,
        "benign_marker": benign_marker,
        "push_command": push_command,
        "push_marker": push_marker,
        "non_shell_fixture": non_shell_fixture,
    }
    prompts = {
        SKILL_PROBE: "Invoke the native skill tool exactly once for each of these names: code, status, kickoff, wrap. Do not use any other tool except exec_structured_output afterward.",
        RELOAD_PROBE: f"Configuration was freshly loaded for this exec. Invoke shell_exec exactly once with command JSON {json.dumps(reload_command)}. Do not alter it. Then finish.",
        BENIGN_PROBE: f"Invoke shell_exec exactly once with command JSON {json.dumps(benign_command)}. Do not alter it. Then finish.",
        PUSH_PROBE: f"Invoke shell_exec exactly once with command JSON {json.dumps(push_command)}. This is an isolated fixture and must be denied by the installed pre-tool hook. Do not alter it. Then finish.",
        NON_SHELL_PROBE: f"Invoke file_read exactly once with path {canonical(non_shell_fixture)!r}. Do not invoke shell_exec. Then finish.",
    }
    return context, prompts


def write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Generate release evidence using actual isolated Polytoken exec traces.")
    for option in ("isolated-home", "config-dir", "auth-dir", "data-dir", "session-dir", "log-dir", "working-dir", "evidence", "config", "hook-template", "bridge", "push-guard", "commit-guard"):
        result.add_argument(f"--{option}", required=True)
    result.add_argument("--skill-path", action="append", required=True)
    result.add_argument("--polytoken-bin", default="polytoken")
    result.add_argument("--machine-id", default="/etc/machine-id", help=argparse.SUPPRESS)
    result.add_argument("--model", help="optional explicit model; otherwise isolated config default")
    result.add_argument("--timeout", type=int, default=300)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.timeout < 1:
            raise AdmissionError("--timeout must be positive")
        paths = {name: Path(getattr(args, name)).expanduser().resolve() for name in ("isolated_home", "config_dir", "auth_dir", "data_dir", "session_dir", "log_dir", "working_dir", "evidence", "config", "hook_template", "bridge", "push_guard", "commit_guard")}
        for name in ("isolated_home", "config_dir", "auth_dir", "data_dir", "session_dir", "log_dir", "working_dir"):
            if not paths[name].is_dir():
                raise AdmissionError(f"--{name.replace('_', '-')} must already exist: {paths[name]}")
        live = {
            (Path.home() / ".config/polytoken").resolve(),
            (Path.home() / ".local/share/polytoken").resolve(),
        }
        if any(paths[name] in live for name in ("config_dir", "auth_dir", "session_dir", "log_dir")):
            raise AdmissionError("refusing to use a live default Polytoken config/auth/session/log directory")
        if any(paths["evidence"].is_relative_to(paths[name]) for name in ("config_dir", "session_dir", "log_dir")):
            raise AdmissionError("--evidence must be outside config, session, and log trees")
        if paths["config"] != paths["config_dir"] / "hooks.json":
            raise AdmissionError("--config must equal <config-dir>/hooks.json")

        skill_paths = [Path(value).expanduser().resolve() for value in args.skill_path]
        expected_names = ADMITTED_SKILLS
        if [path.parent.name for path in skill_paths] != list(expected_names):
            raise AdmissionError("--skill-path must list code,status,kickoff,wrap SKILL.md paths in that order")
        if any(path.name != "SKILL.md" or not path.is_relative_to(paths["config_dir"]) for path in skill_paths):
            raise AdmissionError("each --skill-path must be an isolated config SKILL.md")

        xdg_config = paths["config_dir"].parent
        xdg_data = paths["data_dir"]
        if paths["config_dir"] != xdg_config / "polytoken":
            raise AdmissionError("--config-dir must equal <isolated XDG_CONFIG_HOME>/polytoken")
        if not paths["auth_dir"].is_relative_to(xdg_config) or not paths["session_dir"].is_relative_to(xdg_data) or not paths["log_dir"].is_relative_to(xdg_data):
            raise AdmissionError("auth must be under isolated config; sessions/logs must be under explicit isolated --data-dir")
        allowed_environment = {
            "PATH", "USER", "LOGNAME", "LANG", "LC_ALL", "TERM", "SHELL",
            "SSL_CERT_FILE", "SSL_CERT_DIR", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
            "http_proxy", "https_proxy", "no_proxy",
        }
        env = {key: value for key, value in os.environ.items() if key in allowed_environment}
        env.update(
            HOME=str(paths["isolated_home"]),
            XDG_CONFIG_HOME=str(xdg_config),
            XDG_DATA_HOME=str(xdg_data),
            POLYTOKEN_HOME=str(paths["config_dir"]),
            POLYTOKEN_AUTH_DIR=str(paths["auth_dir"]),
            POLYTOKEN_SESSION_DIR=str(paths["session_dir"]),
            POLYTOKEN_LOG_DIR=str(paths["log_dir"]),
            POLYTOKEN_DATA_PATH=str(xdg_data),
        )
        base = [args.polytoken_bin, "--working-dir", str(paths["working_dir"])]
        started_at = utc_now()
        version_record = run([args.polytoken_bin, "--version"], env, paths["working_dir"], min(args.timeout, 30))
        if version_record["returncode"] != 0 or not version_record["stdout"].strip():
            raise AdmissionError("Polytoken version check failed; no evidence written")

        validators = []
        for path in skill_paths:
            record = run([args.polytoken_bin, "validate", "skill", str(path)], env, paths["working_dir"], args.timeout)
            validators.append({"path": canonical(path), "sha256": digest(path), "result": "pass" if record["returncode"] == 0 else "fail", "subprocess": record})
        doctor = run([args.polytoken_bin, "--working-dir", str(paths["working_dir"]), "doctor", "--format", "json"], env, paths["working_dir"], args.timeout)

        context, prompts = probe_contract(paths["working_dir"])
        for marker_name in ("benign_marker", "push_marker"):
            marker = context[marker_name]
            if marker.exists():
                raise AdmissionError(f"remove pre-existing probe sentinel before admission: {marker}")
        context["non_shell_fixture"].write_text("non-shell fixture\n", encoding="utf-8")
        nonexistent_remote = paths["working_dir"] / ".proptermaltwo-nonexistent-remote"
        if nonexistent_remote.exists():
            raise AdmissionError(f"remove pre-existing fixture remote path: {nonexistent_remote}")
        runtime_checks: dict[str, Any] = {}
        for name in RUNTIME_PROBES:
            command = base + ["exec", "--print-session-logs", "--max-tool-turns", "8"]
            if args.model:
                command.extend(("--model", args.model))
            command.append(prompts[name])
            record = run(command, env, paths["working_dir"], args.timeout)
            result, observation = runtime_result(name, record, context)
            runtime_checks[name] = {"result": result, "subprocess": record, "supporting_subprocesses": [], "observation": observation}

        # Doctor is separate startup/global-hook load evidence; keep both raw
        # process records intact rather than concatenating their streams.
        hook = runtime_checks[RELOAD_PROBE]
        hook["supporting_subprocesses"].extend((version_record, doctor))
        if doctor["returncode"] != 0:
            hook["result"] = "fail"
            hook["observation"] = "Polytoken doctor failed startup/config/global-hook loading"

        evidence = {
            "schema_version": SCHEMA_VERSION,
            "started_at": started_at,
            "ended_at": utc_now(),
            "machine_binding_sha256": digest(Path(args.machine_id)),
            "polytoken_version": version_record["stdout"].strip(),
            "admission_script": bound_file(Path(__file__)),
            "polytoken_binary": bound_file(Path(args.polytoken_bin)),
            "installed_config": bound_file(paths["config"]),
            "guard_inputs": {
                "hook_template": bound_file(paths["hook_template"]),
                "bridge": bound_file(paths["bridge"]),
                "push_guard": bound_file(paths["push_guard"]),
                "commit_guard": bound_file(paths["commit_guard"]),
            },
            "validators": validators,
            "runtime_checks": runtime_checks,
        }
        write_atomic(paths["evidence"], evidence)
        passed = all(item["result"] == "pass" for item in validators) and all(item["result"] == "pass" for item in runtime_checks.values())
        if passed:
            print(f"PASS: wrote fresh Polytoken admission evidence to {paths['evidence']}")
            return 0
        print(f"BLOCKED: wrote truthful failing Polytoken admission evidence to {paths['evidence']}")
        print("Remediation: inspect preserved validator/doctor/exec traces, repair the isolated runtime, and rerun.")
        return 1
    except AdmissionError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        print("Remediation: prepare explicit isolated config, auth, session, log, home, work, and evidence paths, then rerun.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
