#!/usr/bin/env python3
"""Translate Codex or Polytoken pre-tool events into canonical identity guards."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

TIMEOUT_SECONDS = 15
CODEX_DENY_CANARY = "proptermaltwo-codex-pretool-deny-v1"


def bounded(message: str, limit: int = 1200) -> str:
    compact = " ".join(message.split())
    return compact[:limit] if compact else "identity guard could not decide"


def codex_deny(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": bounded(f"{CODEX_DENY_CANARY}: {reason}"),
        }
    }


def polytoken_deny(reason: str) -> dict:
    return {"outcome": "deny", "reason": bounded(reason)}


def emit_deny(host: str, reason: str) -> int:
    payload = codex_deny(reason) if host == "codex" else polytoken_deny(reason)
    json.dump(payload, sys.stdout, separators=(",", ":"))
    return 0


def emit_allow(host: str, diagnostic: str | None = None) -> int:
    if diagnostic:
        print(bounded(diagnostic), file=sys.stderr)
    if host == "polytoken":
        json.dump({"outcome": "allow"}, sys.stdout, separators=(",", ":"))
    return 0


def normalize(host: str, data: object) -> tuple[dict | None, str | None]:
    if not isinstance(data, dict):
        return None, "hook input must be a JSON object"
    if host == "codex":
        if data.get("hook_event_name") != "PreToolUse":
            return None, "expected Codex PreToolUse event"
        if data.get("tool_name") != "Bash":
            return None, "expected Codex Bash tool"
        tool_input = data.get("tool_input")
        if not isinstance(tool_input, dict):
            return None, "Codex tool_input must be an object"
        command = tool_input.get("command")
        cwd = tool_input.get("cwd") or data.get("cwd") or ""
    else:
        if data.get("event") != "pre_tool_use":
            return None, "expected Polytoken pre_tool_use event"
        if data.get("tool_name") != "shell_exec":
            return None, "expected Polytoken shell_exec tool"
        tool_input = data.get("input")
        if not isinstance(tool_input, dict):
            return None, "Polytoken input must be an object"
        command = tool_input.get("command")
        cwd = tool_input.get("cwd") or data.get("cwd") or os.environ.get("POLYTOKEN_PROJECT_DIR", "")
    if not isinstance(command, str) or not command:
        return None, "shell command is missing or is not a string"
    if not isinstance(cwd, str):
        cwd = ""
    return {"tool_input": {"command": command, "cwd": cwd}, "cwd": cwd}, None


def canonical_deny(stdout: str) -> tuple[bool, str]:
    text = stdout.strip()
    if not text:
        return False, ""
    try:
        payload = json.loads(text)
        specific = payload["hookSpecificOutput"]
        if set(specific) != {
            "hookEventName",
            "permissionDecision",
            "permissionDecisionReason",
        }:
            raise ValueError("unexpected canonical output fields")
        if specific["hookEventName"] != "PreToolUse" or specific["permissionDecision"] != "deny":
            raise ValueError("canonical output is not a PreToolUse deny")
        reason = specific["permissionDecisionReason"]
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("canonical deny has no reason")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"malformed canonical guard output: {exc}") from exc
    return True, reason


def guard_path(kind: str) -> Path:
    hooks_dir = Path(__file__).resolve().parent
    name = "gh-identity-guard.py" if kind == "push" else "gh-commit-author-guard.py"
    return hooks_dir / name


def run(host: str, kind: str, raw: str) -> int:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        if kind == "push":
            return emit_deny(host, f"invalid host hook JSON: {exc}")
        return emit_allow(host, f"commit identity hook configuration error: invalid JSON ({exc})")

    normalized, error = normalize(host, data)
    if error:
        if kind == "push":
            return emit_deny(host, f"push identity hook configuration error: {error}")
        return emit_allow(host, f"commit identity hook configuration error: {error}")

    try:
        guard_env = os.environ.copy()
        if "PROPTERMALTWO_GH_IDENTITY_MAP" not in guard_env and "CLAUDE_GH_IDENTITY_MAP" not in guard_env:
            guard_env["PROPTERMALTWO_GH_IDENTITY_MAP"] = str(Path(__file__).resolve().parent / "github-identity-map.json")
        proc = subprocess.run(
            [sys.executable, str(guard_path(kind))],
            input=json.dumps(normalized),
            text=True,
            capture_output=True,
            timeout=TIMEOUT_SECONDS,
            env=guard_env,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"canonical guard exited {proc.returncode}: {proc.stderr}")
        denied, reason = canonical_deny(proc.stdout)
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as exc:
        if kind == "push":
            return emit_deny(host, f"push identity policy failed: {exc}")
        return emit_allow(host, f"commit identity policy diagnostic: {exc}")

    if denied:
        return emit_deny(host, reason)
    if proc.stderr.strip():
        print(bounded(proc.stderr), file=sys.stderr)
    return emit_allow(host)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", choices=("codex", "polytoken"), required=True)
    parser.add_argument("--guard", choices=("push", "commit"), required=True)
    args = parser.parse_args()
    return run(args.host, args.guard, sys.stdin.read())


if __name__ == "__main__":
    raise SystemExit(main())
