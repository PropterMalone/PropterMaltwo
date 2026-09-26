from __future__ import annotations

import json
from pathlib import Path
import re
import shlex
import unittest

ROOT = Path(__file__).resolve().parents[1]
ADAPTERS = ROOT / "adapters"

FROZEN_FILES = {
    "shared/host-hook-bridge.py",
    "codex/AGENTS.md",
    "codex/hooks.json.tmpl",
    "codex/skills/code/SKILL.md",
    "codex/skills/kickoff/SKILL.md",
    "codex/skills/wrap/SKILL.md",
    "polytoken/AGENTS.md",
    "polytoken/hooks.json.tmpl",
    "polytoken/skills/code/SKILL.md",
    "polytoken/skills/kickoff/SKILL.md",
    "polytoken/skills/wrap/SKILL.md",
    "copilot/copilot-instructions.md",
}
SKILLS = {
    host: {
        name: ADAPTERS / host / "skills" / name / "SKILL.md"
        for name in ("code", "kickoff", "wrap")
    }
    for host in ("codex", "polytoken")
}


def frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        raise AssertionError(f"missing frontmatter: {path}")
    values: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep:
            values[key.strip()] = value.strip().strip('"')
    return values


class AdapterContracts(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ADAPTERS / relative).read_text(encoding="utf-8")

    def test_adapter_source_directories_equal_frozen_file_set(self) -> None:
        actual = {
            path.relative_to(ADAPTERS).as_posix()
            for path in ADAPTERS.rglob("*")
            if path.is_file()
        }
        self.assertEqual(actual, FROZEN_FILES)

    def test_every_skill_is_single_file_with_exact_frontmatter_name(self) -> None:
        for host, skills in SKILLS.items():
            for name, path in skills.items():
                with self.subTest(host=host, skill=name):
                    self.assertEqual(
                        [p.name for p in path.parent.iterdir() if p.is_file()],
                        ["SKILL.md"],
                    )
                    metadata = frontmatter(path)
                    self.assertEqual(metadata.get("name"), name)
                    self.assertTrue(metadata.get("description"))
                    self.assertNotIn("agents", {p.name for p in path.parent.iterdir()})

    def test_codex_hooks_are_exact_two_documented_pretooluse_groups(self) -> None:
        payload = json.loads(self.read("codex/hooks.json.tmpl"))
        self.assertEqual(set(payload), {"hooks"})
        self.assertEqual(set(payload["hooks"]), {"PreToolUse"})
        groups = payload["hooks"]["PreToolUse"]
        self.assertEqual(len(groups), 2)
        expected_commands = [
            "python3 {{BRIDGE_PATH_SHELL_QUOTED}} --guard push --host codex",
            "python3 {{BRIDGE_PATH_SHELL_QUOTED}} --guard commit --host codex",
        ]
        for group, command in zip(groups, expected_commands, strict=True):
            self.assertEqual(set(group), {"matcher", "hooks"})
            self.assertEqual(group["matcher"], "^Bash$")
            self.assertEqual(group["hooks"], [{"type": "command", "command": command}])

    def test_polytoken_hooks_are_exact_two_shell_exec_entries(self) -> None:
        payload = json.loads(self.read("polytoken/hooks.json.tmpl"))
        self.assertEqual(len(payload), 2)
        expected = [
            (
                "proptermaltwo-gh-push-identity",
                "python3 {{BRIDGE_PATH_SHELL_QUOTED}} --host polytoken --guard push",
            ),
            (
                "proptermaltwo-gh-commit-author",
                "python3 {{BRIDGE_PATH_SHELL_QUOTED}} --host polytoken --guard commit",
            ),
        ]
        for entry, (name, command) in zip(payload, expected, strict=True):
            self.assertEqual(set(entry), {"name", "event", "matcher", "handler"})
            self.assertEqual(entry["name"], name)
            self.assertEqual(entry["event"], "pre_tool_use")
            self.assertEqual(entry["matcher"], "shell_exec")
            self.assertEqual(entry["handler"], {"bash": command})

    def test_hook_templates_use_renderer_shell_quoted_bridge_contract(self) -> None:
        bridge = "/tmp/operator's config/host-hook-bridge.py"
        # The renderer must JSON-escape the already shell-quoted value before
        # replacing a token inside a JSON string.
        rendered_token = json.dumps(shlex.quote(bridge))[1:-1]
        for host in ("codex", "polytoken"):
            source = self.read(f"{host}/hooks.json.tmpl")
            with self.subTest(host=host):
                self.assertEqual(source.count("{{BRIDGE_PATH_SHELL_QUOTED}}"), 2)
                self.assertNotIn("{{HOST_HOOK_BRIDGE}}", source)
                self.assertNotIn("{{BRIDGE_PATH}}", source)
                # The template owns no quotes around this token; the rendered
                # interior includes both POSIX shell quoting and JSON escaping.
                rendered = source.replace("{{BRIDGE_PATH_SHELL_QUOTED}}", rendered_token)
                self.assertNotIn("{{", rendered)
                payload = json.loads(rendered)
                commands = (
                    [group["hooks"][0]["command"] for group in payload["hooks"]["PreToolUse"]]
                    if host == "codex"
                    else [entry["handler"]["bash"] for entry in payload]
                )
                for command in commands:
                    argv = shlex.split(command)
                    self.assertEqual(argv[0:2], ["python3", bridge])
                    self.assertEqual(argv.count(bridge), 1)

    def test_polytoken_uses_shipped_subagent_plan_and_execute(self) -> None:
        agents = self.read("polytoken/AGENTS.md")
        code = SKILLS["polytoken"]["code"].read_text(encoding="utf-8")
        self.assertIn("shipped `subagent` tool", agents)
        self.assertIn("shipped `plan`", agents)
        self.assertIn("`execute` facet", agents)
        self.assertIn("`general-purpose`, `count: 1`", code)
        self.assertIn("structured completion sink", code)
        self.assertIn("asynchronous job handle", code)
        self.assertNotIn("model:", code)

    def test_lifecycle_memory_orientation_is_explicit_and_bounded(self) -> None:
        for host in SKILLS:
            kickoff = SKILLS[host]["kickoff"].read_text(encoding="utf-8")
            with self.subTest(host=host):
                self.assertIn("PROPTERMALTWO_MEMORY_DIR", kickoff)
                self.assertIn("Memory: unconfigured", kickoff)
                self.assertIn("MEMORY.md", kickoff)
                self.assertIn("handoff_*.md", kickoff)
                self.assertIn("at most three", kickoff)
                self.assertIn("never sweep the full memory tree", kickoff)
                self.assertIn("git status --short", kickoff)
                self.assertIn("git log -1 --oneline", kickoff)
                self.assertIn("Then ask what is on the agenda and stop", kickoff)

    def test_wrap_contract_forbids_unauthorized_actions(self) -> None:
        for host in SKILLS:
            wrap = SKILLS[host]["wrap"].read_text(encoding="utf-8")
            compact = " ".join(wrap.split()).lower()
            authorization = compact.split("## resolve memory", 1)[0]
            with self.subTest(host=host):
                self.assertIn("does not authorize", authorization)
                for action_stem in ("commit", "push", "publish", "send"):
                    self.assertIn(action_stem, authorization)
                self.assertIn("git status --short", compact)
                self.assertIn("handoff_yyyy-mm-dd.md", compact)
                self.assertIn("name every file written", compact)
                self.assertIn("command run", compact)
                self.assertRegex(compact, r"do not (start|launch) a (review )?subagent automatically")
                self.assertIn("ask before writing", compact)

    def test_code_contract_has_structured_completion_and_no_auto_git(self) -> None:
        for host in SKILLS:
            code = SKILLS[host]["code"].read_text(encoding="utf-8")
            with self.subTest(host=host):
                for heading in ("### Summary", "### Tests", "### Validation", "### Blockers"):
                    self.assertIn(heading, code)
                self.assertIn("Do not", code)
                self.assertIn("commit", code)
                self.assertIn("push", code)
                self.assertIn("leave changes unstaged", " ".join(code.split()).lower())

    def test_new_host_assets_have_no_active_claude_runtime_dependency(self) -> None:
        forbidden = (
            "/home/",
            "~/.claude/",
            "claude -p",
            "ccusage",
            "Agent` tool",
            "run_in_background",
        )
        for host in ("codex", "polytoken"):
            for path in (ADAPTERS / host).rglob("*"):
                if not path.is_file():
                    continue
                text = path.read_text(encoding="utf-8")
                with self.subTest(host=host, path=path.name):
                    for token in forbidden:
                        self.assertNotIn(token, text)

    def test_copilot_is_instructions_only_preview(self) -> None:
        text = self.read("copilot/copilot-instructions.md")
        self.assertIn("**preview**", text)
        for unsupported in ("skills", "hooks", "agents", "MCP", "persistent memory"):
            self.assertIn(unsupported, text)
        self.assertNotIn("first-class", text)


if __name__ == "__main__":
    unittest.main()
