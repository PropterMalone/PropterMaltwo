from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BRIDGE_SOURCE = ROOT / "adapters/shared/host-hook-bridge.py"
HOOK_NAMES = (
    "gh-identity-guard.py",
    "gh-commit-author-guard.py",
    "_gh_identity_common.py",
)


class HostHookBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="proptermaltwo-bridge-")
        self.root = Path(self.tmp.name)
        self.hooks = self.root / "hooks"
        self.hooks.mkdir()
        shutil.copy2(BRIDGE_SOURCE, self.hooks / "host-hook-bridge.py")
        for name in HOOK_NAMES:
            shutil.copy2(ROOT / "hooks" / name, self.hooks / name)
        self.map_path = self.root / "identity-map.json"
        self.map_path.write_text(json.dumps({"identities": {}}), encoding="utf-8")
        self.repo = self.root / "repo"
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def event(self, host: str, command: str) -> dict:
        if host == "codex":
            return {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": command},
                "cwd": str(self.repo),
            }
        return {
            "event": "pre_tool_use",
            "tool_name": "shell_exec",
            "input": {"command": command},
            "cwd": str(self.repo),
        }

    def fire(
        self,
        host: str,
        guard: str,
        event: dict | str,
        extra_env: dict[str, str] | None = None,
        *,
        inject_map: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.pop("PROPTERMALTWO_GH_IDENTITY_MAP", None)
        env.pop("CLAUDE_GH_IDENTITY_MAP", None)
        if inject_map:
            env["PROPTERMALTWO_GH_IDENTITY_MAP"] = str(self.map_path)
        if extra_env:
            env.update(extra_env)
        raw = event if isinstance(event, str) else json.dumps(event)
        return subprocess.run(
            [sys.executable, str(self.hooks / "host-hook-bridge.py"),
             "--host", host, "--guard", guard],
            input=raw,
            text=True,
            capture_output=True,
            timeout=30,
            env=env,
        )

    def assert_allow(self, host: str, proc: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(proc.returncode, 0, proc.stderr)
        if host == "codex":
            self.assertEqual(proc.stdout, "")
        else:
            self.assertEqual(json.loads(proc.stdout), {"outcome": "allow"})

    def assert_deny(self, host: str, proc: subprocess.CompletedProcess[str]) -> str:
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        if host == "codex":
            self.assertEqual(set(payload), {"hookSpecificOutput"})
            specific = payload["hookSpecificOutput"]
            self.assertEqual(
                set(specific),
                {"hookEventName", "permissionDecision", "permissionDecisionReason"},
            )
            self.assertEqual(specific["hookEventName"], "PreToolUse")
            self.assertEqual(specific["permissionDecision"], "deny")
            self.assertTrue(specific["permissionDecisionReason"].startswith("proptermaltwo-codex-pretool-deny-v1: "))
            return specific["permissionDecisionReason"]
        self.assertEqual(set(payload), {"outcome", "reason"})
        self.assertEqual(payload["outcome"], "deny")
        return payload["reason"]

    def test_unrelated_commands_not_overblocked(self) -> None:
        for host in ("codex", "polytoken"):
            for guard in ("push", "commit"):
                with self.subTest(host=host, guard=guard):
                    self.assert_allow(host, self.fire(host, guard, self.event(host, "printf ok")))

    def test_push_invalid_host_json_denies_commit_allows_with_diagnostic(self) -> None:
        for host in ("codex", "polytoken"):
            push = self.fire(host, "push", "not-json")
            self.assertIn("invalid host hook JSON", self.assert_deny(host, push))
            commit = self.fire(host, "commit", "not-json")
            self.assert_allow(host, commit)
            self.assertIn("configuration error", commit.stderr)

    def test_wrong_tool_push_denies_commit_allows(self) -> None:
        for host in ("codex", "polytoken"):
            event = self.event(host, "printf ok")
            event["tool_name"] = "file_read"
            self.assertIn("expected", self.assert_deny(host, self.fire(host, "push", event)))
            self.assert_allow(host, self.fire(host, "commit", event))

    def test_untagged_push_is_native_deny(self) -> None:
        for host in ("codex", "polytoken"):
            reason = self.assert_deny(host, self.fire(host, "push", self.event(host, "git push")))
            self.assertIn("not tagged", reason)
            self.assertIn("proptermaltwo.identity", reason)

    def test_neutral_repo_key_preferred_and_legacy_fallback(self) -> None:
        # Empty map makes either recognized tag fail as an unknown identity, proving it was read.
        for key in ("proptermaltwo.identity", "claude.identity"):
            subprocess.run(["git", "-C", str(self.repo), "config", "--unset-all", "proptermaltwo.identity"], check=False)
            subprocess.run(["git", "-C", str(self.repo), "config", "--unset-all", "claude.identity"], check=False)
            subprocess.run(["git", "-C", str(self.repo), "config", key, "fixture"], check=True)
            reason = self.assert_deny("polytoken", self.fire("polytoken", "push", self.event("polytoken", "git push")))
            self.assertIn("not in the identity map", reason)

    def test_conflicting_repo_keys_deny_both_guards(self) -> None:
        subprocess.run(["git", "-C", str(self.repo), "config", "proptermaltwo.identity", "one"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "claude.identity", "two"], check=True)
        for guard in ("push", "commit"):
            command = "git push" if guard == "push" else "git commit -m fixture"
            reason = self.assert_deny("polytoken", self.fire("polytoken", guard, self.event("polytoken", command)))
            self.assertIn("identity conflict", reason.lower())

    def test_conflicting_map_variables_push_deny_commit_allow(self) -> None:
        other = self.root / "other-map.json"
        other.write_text('{"identities":{}}', encoding="utf-8")
        extra = {"CLAUDE_GH_IDENTITY_MAP": str(other)}
        self.assertIn("configuration conflict", self.assert_deny(
            "codex", self.fire("codex", "push", self.event("codex", "git push"), extra)
        ))
        commit = self.fire("codex", "commit", self.event("codex", "git commit -m x"), extra)
        self.assert_allow("codex", commit)

    def test_new_host_default_map_is_sibling_neutral_path_not_claude_home(self) -> None:
        home = self.root / "isolated-home"
        legacy = home / ".claude/github-identity-map.json"
        legacy.parent.mkdir(parents=True)
        legacy.write_text(json.dumps({"identities": {"fixture": {"github_login": "wrong"}}}), encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "config", "proptermaltwo.identity", "fixture"], check=True)
        for host in ("codex", "polytoken"):
            with self.subTest(host=host):
                reason = self.assert_deny(
                    host,
                    self.fire(
                        host,
                        "push",
                        self.event(host, "git push"),
                        {"HOME": str(home)},
                        inject_map=False,
                    ),
                )
                self.assertIn(str(self.hooks / "github-identity-map.json"), reason)
                self.assertNotIn(str(legacy), reason)

    def test_neutral_one_shot_identity_precedence_fallback_and_conflict(self) -> None:
        for variable in ("PROPTERMALTWO_IDENTITY", "CLAUDE_IDENTITY"):
            with self.subTest(variable=variable):
                event = self.event("polytoken", f"{variable}=fixture gh repo create --source . --push")
                event["cwd"] = str(self.root)
                reason = self.assert_deny("polytoken", self.fire("polytoken", "push", event))
                self.assertIn("not in the identity map", reason)

        event = self.event(
            "polytoken",
            "PROPTERMALTWO_IDENTITY=one CLAUDE_IDENTITY=two "
            "gh repo create --source . --push",
        )
        event["cwd"] = str(self.root)
        reason = self.assert_deny("polytoken", self.fire("polytoken", "push", event))
        self.assertIn("environment conflict", reason.lower())
        self.assertIn("PROPTERMALTWO_IDENTITY", reason)

    def test_neutral_override_precedence_fallback_and_conflict(self) -> None:
        for variable in ("PROPTERMALTWO_IDENTITY_OVERRIDE", "CLAUDE_IDENTITY_OVERRIDE"):
            with self.subTest(variable=variable):
                reason = self.assert_deny(
                    "codex",
                    self.fire("codex", "push", self.event("codex", f"{variable}=fixture git push")),
                )
                self.assertIn("not in the identity map", reason)

        reason = self.assert_deny(
            "codex",
            self.fire(
                "codex",
                "push",
                self.event(
                    "codex",
                    "PROPTERMALTWO_IDENTITY_OVERRIDE=one "
                    "CLAUDE_IDENTITY_OVERRIDE=two git push",
                ),
            ),
        )
        self.assertIn("environment conflict", reason.lower())
        self.assertIn("PROPTERMALTWO_IDENTITY_OVERRIDE", reason)

    def test_missing_command_push_denies_commit_allows_with_diagnostic(self) -> None:
        for host in ("codex", "polytoken"):
            event = self.event(host, "placeholder")
            container = event["tool_input"] if host == "codex" else event["input"]
            del container["command"]
            self.assertIn("missing", self.assert_deny(host, self.fire(host, "push", event)))
            commit = self.fire(host, "commit", event)
            self.assert_allow(host, commit)
            self.assertIn("configuration error", commit.stderr)

    def test_unparseable_command_uses_tight_push_fallback(self) -> None:
        for host in ("codex", "polytoken"):
            reason = self.assert_deny(host, self.fire(host, "push", self.event(host, 'git push "')))
            self.assertIn("parse", reason.lower())
            self.assert_allow(host, self.fire(host, "push", self.event(host, 'printf "')))

    def test_policy_crash_and_malformed_output_follow_guard_specific_posture(self) -> None:
        failures = {
            "crash": "raise SystemExit(7)\n",
            "malformed": "print('not-json')\n",
        }
        for label, source in failures.items():
            for guard in ("push", "commit"):
                target = self.hooks / (
                    "gh-identity-guard.py" if guard == "push" else "gh-commit-author-guard.py"
                )
                target.write_text(source, encoding="utf-8")
                for host in ("codex", "polytoken"):
                    with self.subTest(failure=label, guard=guard, host=host):
                        proc = self.fire(host, guard, self.event(host, "git push"))
                        if guard == "push":
                            self.assertIn("policy failed", self.assert_deny(host, proc))
                        else:
                            self.assert_allow(host, proc)
                            self.assertIn("policy diagnostic", proc.stderr)

    def test_policy_timeout_follows_guard_specific_posture(self) -> None:
        bridge = self.hooks / "host-hook-bridge.py"
        bridge.write_text(
            bridge.read_text(encoding="utf-8").replace("TIMEOUT_SECONDS = 15", "TIMEOUT_SECONDS = 0.05"),
            encoding="utf-8",
        )
        sleeper = "import time\ntime.sleep(1)\n"
        for guard in ("push", "commit"):
            target = self.hooks / (
                "gh-identity-guard.py" if guard == "push" else "gh-commit-author-guard.py"
            )
            target.write_text(sleeper, encoding="utf-8")
            for host in ("codex", "polytoken"):
                with self.subTest(guard=guard, host=host):
                    proc = self.fire(host, guard, self.event(host, "git push"))
                    if guard == "push":
                        self.assertIn("timed out", self.assert_deny(host, proc))
                    else:
                        self.assert_allow(host, proc)
                        self.assertIn("timed out", proc.stderr)


if __name__ == "__main__":
    unittest.main()
