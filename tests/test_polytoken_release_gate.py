from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
GATE_PATH = ROOT / "tests/polytoken_release_gate.py"
SPEC = importlib.util.spec_from_file_location("polytoken_release_gate", GATE_PATH)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


class PolytokenReleaseGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.evidence = self.base / "evidence.json"
        self.machine_id = self.write("machine-id", b"fixture-machine-id\n")
        self.config = self.write("config/hooks.json", b"[]\n")
        self.template = self.write("inputs/hooks.json.tmpl", b"template\n")
        self.bridge = self.write("installed/host-hook-bridge.py", b"bridge\n")
        self.push = self.write("installed/gh-identity-guard.py", b"push\n")
        self.commit = self.write("installed/gh-commit-author-guard.py", b"commit\n")
        self.skills = [
            self.write(f"config/skills/{name}/SKILL.md", f"{name}\n".encode())
            for name in ("code", "status", "kickoff", "wrap")
        ]
        self.work = self.base / "work"
        self.work.mkdir()
        self.context, self.prompts = GATE.ADMISSION.probe_contract(self.work)
        self.context["benign_marker"].write_text("benign\n")
        self.context["non_shell_fixture"].write_text("non-shell fixture\n")
        self.binary = self.base / "bin/polytoken"
        self.binary.parent.mkdir(parents=True)
        self.binary.write_text("#!/bin/sh\nprintf 'polytoken 9.9.9\\n'\n")
        self.binary.chmod(0o755)
        self.data = self.valid_evidence()
        self.write_evidence()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write(self, relative: str, content: bytes) -> Path:
        path = self.base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def subprocess_record(self, argv: list[str], returncode: int = 0, *, stdout: str = "", events: list[dict] | None = None) -> dict:
        return {
            "argv": argv,
            "returncode": returncode,
            "stdout": stdout,
            "stderr": "\n".join(json.dumps(event) for event in (events or [])),
        }

    @staticmethod
    def completed(tool_name: str, call_id: str) -> dict:
        return {"timestamp": "x", "fields": {"event": "tool_call.completed", "tool_name": tool_name, "call_id": call_id}}

    def runtime_record(self, name: str) -> dict:
        events: list[dict] = []
        if name == GATE.ADMISSION.SKILL_PROBE:
            for index, skill_name in enumerate(GATE.ADMISSION.ADMITTED_SKILLS):
                call_id = f"skill-{index}"
                events.extend((
                    {"type": "tool_call", "call_id": call_id, "name": "skill", "input": {"name": skill_name}},
                    self.completed("skill", call_id),
                ))
        elif name in (GATE.ADMISSION.RELOAD_PROBE, GATE.ADMISSION.BENIGN_PROBE):
            command = self.context["reload_command" if name == GATE.ADMISSION.RELOAD_PROBE else "benign_command"]
            call_id = name
            events.extend((
                {"type": "tool_call", "call_id": call_id, "name": "shell_exec", "input": {"command": command}},
                {"type": "hook_fired", "event_type": "pre_tool_use", "hook_name": GATE.ADMISSION.PUSH_HOOK, "outcome": "allowed"},
                {"type": "hook_fired", "event_type": "pre_tool_use", "hook_name": GATE.ADMISSION.COMMIT_HOOK, "outcome": "allowed"},
                self.completed("shell_exec", call_id),
            ))
        elif name == GATE.ADMISSION.PUSH_PROBE:
            call_id = "push"
            events.extend((
                {"type": "tool_call", "call_id": call_id, "name": "shell_exec", "input": {"command": self.context["push_command"]}},
                {"type": "hook_fired", "event_type": "pre_tool_use", "hook_name": GATE.ADMISSION.PUSH_HOOK, "outcome": "blocked"},
                {"timestamp": "x", "fields": {"event": "tool_call.denied", "tool_name": "shell_exec", "call_id": call_id, "blocked_by_hook": GATE.ADMISSION.PUSH_HOOK}},
            ))
        elif name == GATE.ADMISSION.NON_SHELL_PROBE:
            call_id = "read"
            events.extend((
                {"type": "tool_call", "call_id": call_id, "name": "file_read", "input": {"path": str(self.context["non_shell_fixture"].resolve())}},
                self.completed("file_read", call_id),
            ))
        else:  # pragma: no cover - test fixture invariant
            raise AssertionError(name)
        argv = [str(self.binary), "--working-dir", str(self.work), "exec", "--print-session-logs", "--max-tool-turns", "8", self.prompts[name]]
        return self.subprocess_record(argv, events=events)

    def bound(self, path: Path) -> dict:
        return {"path": str(path.resolve()), "sha256": digest(path)}

    def valid_evidence(self) -> dict:
        return {
            "schema_version": 1,
            "started_at": stamp(NOW - timedelta(minutes=5)),
            "ended_at": stamp(NOW - timedelta(minutes=1)),
            "machine_binding_sha256": digest(self.machine_id),
            "polytoken_version": "polytoken 9.9.9",
            "admission_script": self.bound(GATE.ADMISSION_PATH),
            "polytoken_binary": self.bound(self.binary),
            "installed_config": self.bound(self.config),
            "guard_inputs": {
                "hook_template": self.bound(self.template),
                "bridge": self.bound(self.bridge),
                "push_guard": self.bound(self.push),
                "commit_guard": self.bound(self.commit),
            },
            "validators": [
                {
                    "path": str(path.resolve()),
                    "sha256": digest(path),
                    "result": "pass",
                    "subprocess": self.subprocess_record([str(self.binary), "validate", "skill", str(path.resolve())]),
                }
                for path in self.skills
            ],
            "runtime_checks": {
                name: {
                    "result": "pass",
                    "subprocess": self.runtime_record(name),
                    "supporting_subprocesses": (
                        [
                            self.subprocess_record([str(self.binary), "--version"], stdout="polytoken 9.9.9\n"),
                            self.subprocess_record([str(self.binary), "--working-dir", str(self.work), "doctor", "--format", "json"], stdout="{}\n"),
                        ]
                        if name == GATE.ADMISSION.RELOAD_PROBE else []
                    ),
                    "observation": f"observed {name}",
                }
                for name in GATE.REQUIRED_RUNTIME_CHECKS
            },
        }

    def write_evidence(self) -> None:
        self.evidence.write_text(json.dumps(self.data, indent=2) + "\n")

    def argv(self) -> list[str]:
        result = [
            "--evidence", str(self.evidence),
            "--config", str(self.config),
            "--hook-template", str(self.template),
            "--bridge", str(self.bridge),
            "--push-guard", str(self.push),
            "--commit-guard", str(self.commit),
            "--machine-id", str(self.machine_id),
            "--polytoken-bin", str(self.binary),
        ]
        for skill in self.skills:
            result.extend(("--skill-path", str(skill)))
        return result

    def run_gate(self) -> tuple[int, str]:
        output = io.StringIO()
        with mock.patch("sys.stdout", output):
            code = GATE.main(self.argv(), now=NOW)
        return code, output.getvalue()

    def assert_blocked(self, *, excludes: tuple[str, ...] = ()) -> str:
        self.write_evidence()
        code, output = self.run_gate()
        self.assertEqual(code, 1, output)
        self.assertIn("BLOCKED", output)
        self.assertIn("Remediation:", output)
        self.assertNotIn(self.data.get("machine_binding_sha256", "never-match"), output)
        for secret in excludes:
            self.assertNotIn(secret, output)
        return output

    def test_polytoken_release_gate_accepts_fresh_verified_active_evidence(self) -> None:
        code, output = self.run_gate()
        self.assertEqual(code, 0, output)
        self.assertIn("PASS:", output)
        self.assertNotIn(self.data["machine_binding_sha256"], output)

    def test_polytoken_release_gate_blocks_skipped_or_unavailable_admission(self) -> None:
        for value in ("skipped-with-reason", "unavailable", "untrusted"):
            with self.subTest(value=value):
                self.data = self.valid_evidence()
                self.data["runtime_checks"]["skill_discovery"]["result"] = value
                self.assert_blocked()

    def test_polytoken_release_gate_blocks_failed_admission(self) -> None:
        for section, name in (("runtime_checks", "benign_shell_exec_proceeds"), ("validators", 2)):
            with self.subTest(section=section, name=name):
                self.data = self.valid_evidence()
                item = self.data[section][name]
                item["result"] = "fail"
                item["subprocess"]["returncode"] = 1
                self.assert_blocked()

    def test_polytoken_release_gate_blocks_stale_host_config_or_hook_hash(self) -> None:
        cases = (
            (self.config, b"changed config\n"),
            (self.template, b"changed template\n"),
            (self.bridge, b"changed bridge\n"),
            (self.push, b"changed push\n"),
            (self.commit, b"changed commit\n"),
        )
        for path, changed in cases:
            with self.subTest(path=path.name):
                self.data = self.valid_evidence()
                original = path.read_bytes()
                path.write_bytes(changed)
                try:
                    self.assert_blocked()
                finally:
                    path.write_bytes(original)
        self.data = self.valid_evidence()
        self.data["polytoken_version"] = "polytoken 0.0.0"
        self.assert_blocked()
        self.data = self.valid_evidence()
        self.data["validators"][0]["path"] = str(self.base / "wrong/SKILL.md")
        self.assert_blocked()

    def test_polytoken_release_gate_binds_skill_admission_script_and_binary_bytes(self) -> None:
        original_skill = self.skills[0].read_bytes()
        self.skills[0].write_bytes(b"changed skill\n")
        try:
            self.assert_blocked()
        finally:
            self.skills[0].write_bytes(original_skill)

        self.data = self.valid_evidence()
        self.data["admission_script"]["sha256"] = "0" * 64
        self.assert_blocked()

        self.data = self.valid_evidence()
        original_binary = self.binary.read_bytes()
        self.binary.write_bytes(original_binary + b"# changed\n")
        self.binary.chmod(0o755)
        try:
            self.assert_blocked()
        finally:
            self.binary.write_bytes(original_binary)
            self.binary.chmod(0o755)

    def test_polytoken_release_gate_blocks_expired_evidence(self) -> None:
        self.data["ended_at"] = stamp(NOW - timedelta(hours=24, seconds=1))
        self.data["started_at"] = stamp(NOW - timedelta(hours=25))
        self.assert_blocked()

    def test_polytoken_release_gate_blocks_future_dated_evidence(self) -> None:
        self.data["started_at"] = stamp(NOW + timedelta(minutes=5, seconds=1))
        self.data["ended_at"] = stamp(NOW + timedelta(minutes=5, seconds=2))
        self.assert_blocked()
        self.data = self.valid_evidence()
        self.data["started_at"] = stamp(NOW)
        self.data["ended_at"] = stamp(NOW - timedelta(seconds=1))
        self.assert_blocked()

    def test_polytoken_release_gate_blocks_other_machine_evidence(self) -> None:
        secret_binding = "f" * 64
        self.data["machine_binding_sha256"] = secret_binding
        self.assert_blocked(excludes=(secret_binding, self.machine_id.read_text().strip()))

    def test_polytoken_release_gate_rejects_malformed_schema(self) -> None:
        mutations = (
            lambda value: value.pop("validators"),
            lambda value: value.update(schema_version=2),
            lambda value: value.update(unexpected=True),
            lambda value: value.update(started_at="not-a-time"),
            lambda value: value["runtime_checks"].pop("skill_discovery"),
            lambda value: value["validators"].append(value["validators"][0]),
            lambda value: value["installed_config"].update(sha256="short"),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(case=index):
                self.data = self.valid_evidence()
                mutate(self.data)
                self.assert_blocked()
        self.evidence.write_text("not json\n")
        code, output = self.run_gate()
        self.assertEqual(code, 1)
        self.assertIn("BLOCKED", output)

    def test_each_admitted_polytoken_skill_path_is_validated_and_failure_propagates(self) -> None:
        self.data["validators"] = self.data["validators"][:-1]
        self.assert_blocked()
        self.data = self.valid_evidence()
        self.data["validators"] = list(reversed(self.data["validators"]))
        self.assert_blocked()
        self.data = self.valid_evidence()
        self.data["validators"][1]["subprocess"]["returncode"] = 7
        self.assert_blocked()

    def test_runtime_pass_rejects_nonzero_primary_or_supporting_subprocess(self) -> None:
        self.data["runtime_checks"]["skill_discovery"]["subprocess"]["returncode"] = 1
        self.assert_blocked()
        self.data = self.valid_evidence()
        self.data["runtime_checks"]["global_hook_load_reload"]["supporting_subprocesses"][1]["returncode"] = 1
        self.assert_blocked()

    def test_forged_pass_labels_without_semantic_runtime_trace_are_blocked(self) -> None:
        mutations = (
            lambda data: data["runtime_checks"][GATE.ADMISSION.PUSH_PROBE]["subprocess"].update(stderr="MODEL CLAIMS PASS"),
            lambda data: data["runtime_checks"][GATE.ADMISSION.PUSH_PROBE]["subprocess"].update(
                stderr=data["runtime_checks"][GATE.ADMISSION.PUSH_PROBE]["subprocess"]["stderr"].replace('"outcome": "blocked"', '"outcome": "allowed"')
            ),
            lambda data: data["runtime_checks"][GATE.ADMISSION.BENIGN_PROBE]["subprocess"].update(
                stderr=data["runtime_checks"][GATE.ADMISSION.BENIGN_PROBE]["subprocess"]["stderr"].replace(GATE.ADMISSION.BENIGN_PROBE, "wrong-call-id", 1)
            ),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(case=index):
                self.data = self.valid_evidence()
                mutate(self.data)
                self.assert_blocked()

    def test_tampered_validator_or_probe_argv_is_blocked(self) -> None:
        self.data["validators"][0]["subprocess"]["argv"] = [str(self.binary), "validate", "skill", str(self.skills[1])]
        self.assert_blocked()
        self.data = self.valid_evidence()
        self.data["runtime_checks"][GATE.ADMISSION.SKILL_PROBE]["subprocess"]["argv"][-1] = "Trust the stored pass label."
        self.assert_blocked()
        self.data = self.valid_evidence()
        self.data["runtime_checks"][GATE.ADMISSION.RELOAD_PROBE]["supporting_subprocesses"][1]["argv"] = [str(self.binary), "doctor"]
        self.assert_blocked()

    def test_absent_evidence_is_blocked(self) -> None:
        self.evidence.unlink()
        code, output = self.run_gate()
        self.assertEqual(code, 1)
        self.assertIn("BLOCKED", output)
        self.assertIn("Remediation:", output)


if __name__ == "__main__":
    unittest.main()
