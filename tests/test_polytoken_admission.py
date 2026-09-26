from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import os
import tempfile
import textwrap
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "scripts/polytoken_admission.py"
SPEC = importlib.util.spec_from_file_location("polytoken_admission", RUNNER_PATH)
assert SPEC and SPEC.loader
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class PolytokenAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.home = self.mkdir("home")
        self.config = self.mkdir("config/polytoken")
        self.auth = self.mkdir("config/auth-isolated")
        self.data = self.mkdir("data")
        self.sessions = self.mkdir("data/polytoken/sessions-v1")
        self.logs = self.mkdir("data/polytoken/logs")
        self.work = self.mkdir("work")
        self.evidence = self.base / "evidence/evidence.json"
        self.machine_id = self.write("machine-id", "fake machine id\n")
        self.hooks = self.write("config/polytoken/hooks.json", "[]\n")
        self.template = self.write("inputs/hooks.json.tmpl", "template\n")
        self.bridge = self.write("inputs/host-hook-bridge.py", "bridge\n")
        self.push = self.write("inputs/gh-identity-guard.py", "push\n")
        self.commit = self.write("inputs/gh-commit-author-guard.py", "commit\n")
        self.skills = [self.write(f"config/polytoken/skills/{name}/SKILL.md", f"{name}\n") for name in ("code", "status", "kickoff", "wrap")]
        self.calls = self.base / "calls.jsonl"
        self.binary = self.write("bin/polytoken", self.fake_cli())
        self.binary.chmod(0o755)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def mkdir(self, relative: str) -> Path:
        path = self.base / relative
        path.mkdir(parents=True)
        return path

    def write(self, relative: str, content: str) -> Path:
        path = self.base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def fake_cli(self) -> str:
        return textwrap.dedent(f"""\
            #!{Path('/usr/bin/python3')}
            import json, os, pathlib, sys
            args = sys.argv[1:]
            with open({str(self.calls)!r}, 'a') as handle:
                handle.write(json.dumps({{'argv': args, 'home': os.environ.get('HOME'), 'config': os.environ.get('XDG_CONFIG_HOME'), 'data': os.environ.get('XDG_DATA_HOME'), 'auth': os.environ.get('POLYTOKEN_AUTH_DIR'), 'sessions': os.environ.get('POLYTOKEN_SESSION_DIR'), 'logs': os.environ.get('POLYTOKEN_LOG_DIR'), 'openai': os.environ.get('OPENAI_API_KEY'), 'anthropic': os.environ.get('ANTHROPIC_API_KEY'), 'claude_home': os.environ.get('CLAUDE_HOME')}}) + '\\n')
            if args == ['--version']:
                print('polytoken 9.9.9')
                raise SystemExit(0)
            if 'validate' in args:
                print('valid')
                raise SystemExit(0)
            if 'doctor' in args:
                print(json.dumps({{'summary': {{'failures': 0, 'warnings': 1}}, 'checks': [{{'name':'hooks','status':'pass'}}]}}))
                raise SystemExit(0)
            prompt = args[-1]
            def emit(value): print(json.dumps(value), file=sys.stderr)
            def completed(name, call):
                emit({{'timestamp':'x','fields':{{'event':'tool_call.started','tool_name':name,'call_id':call}}}})
                emit({{'timestamp':'x','fields':{{'event':'tool_call.completed','tool_name':name,'call_id':call}}}})
            if 'native skill tool' in prompt:
                for index, name in enumerate(('code','status','kickoff','wrap')):
                    call=f's{{index}}'; emit({{'type':'tool_call','call_id':call,'name':'skill','input':{{'name':name}}}}); completed('skill',call)
            elif 'reload-probe' in prompt:
                call='reload'; emit({{'type':'tool_call','call_id':call,'name':'shell_exec','input':{{'command':"printf '%s\\\\n' reload-probe"}}}})
                emit({{'type':'hook_fired','event_type':'pre_tool_use','hook_name':'proptermaltwo-gh-push-identity','outcome':'allowed'}})
                emit({{'type':'hook_fired','event_type':'pre_tool_use','hook_name':'proptermaltwo-gh-commit-author','outcome':'allowed'}}); completed('shell_exec',call)
            elif 'benign' in prompt:
                command=json.loads(prompt.split('command JSON ',1)[1].split('. Do not',1)[0])
                marker=pathlib.Path({str(self.work / '.proptermaltwo-benign-shell')!r}); marker.write_text('benign\\n')
                call='benign'; emit({{'type':'tool_call','call_id':call,'name':'shell_exec','input':{{'command':command}}}})
                emit({{'type':'hook_fired','event_type':'pre_tool_use','hook_name':'proptermaltwo-gh-push-identity','outcome':'allowed'}})
                emit({{'type':'hook_fired','event_type':'pre_tool_use','hook_name':'proptermaltwo-gh-commit-author','outcome':'allowed'}}); completed('shell_exec',call)
            elif 'git push --dry-run' in prompt:
                command=json.loads(prompt.split('command JSON ',1)[1].split('. This',1)[0])
                call='push'; emit({{'type':'tool_call','call_id':call,'name':'shell_exec','input':{{'command':command}}}})
                emit({{'type':'hook_fired','event_type':'pre_tool_use','hook_name':'proptermaltwo-gh-push-identity','outcome':'blocked'}})
                emit({{'timestamp':'x','fields':{{'event':'tool_call.denied','tool_name':'shell_exec','call_id':call,'blocked_by_hook':'proptermaltwo-gh-push-identity'}}}})
                emit({{'type':'tool_result','call_id':call,'is_error':True}})
            elif 'file_read exactly once' in prompt:
                path=prompt.split("path '",1)[1].split("'. Do not",1)[0]
                call='read'; emit({{'type':'tool_call','call_id':call,'name':'file_read','input':{{'path':path}}}}); completed('file_read',call)
            print('MODEL PROSE CLAIMS EVERYTHING PASSED')
        """)

    def argv(self) -> list[str]:
        result = [
            "--isolated-home", str(self.home), "--config-dir", str(self.config),
            "--auth-dir", str(self.auth), "--data-dir", str(self.data), "--session-dir", str(self.sessions), "--log-dir", str(self.logs),
            "--working-dir", str(self.work), "--evidence", str(self.evidence), "--config", str(self.hooks),
            "--hook-template", str(self.template), "--bridge", str(self.bridge), "--push-guard", str(self.push),
            "--commit-guard", str(self.commit), "--polytoken-bin", str(self.binary), "--machine-id", str(self.machine_id),
        ]
        for skill in self.skills:
            result.extend(("--skill-path", str(skill)))
        return result

    def test_runner_generates_all_pass_evidence_from_trace_and_sentinels(self) -> None:
        self.assertEqual(RUNNER.main(self.argv()), 0)
        evidence = json.loads(self.evidence.read_text())
        self.assertEqual([item["result"] for item in evidence["validators"]], ["pass"] * 4)
        self.assertEqual([item["sha256"] for item in evidence["validators"]], [RUNNER.digest(path) for path in self.skills])
        self.assertEqual(evidence["admission_script"]["sha256"], RUNNER.digest(RUNNER_PATH))
        self.assertEqual(evidence["polytoken_binary"]["sha256"], RUNNER.digest(self.binary))
        self.assertEqual(set(evidence["runtime_checks"]), set(RUNNER.RUNTIME_PROBES))
        self.assertTrue(all(item["result"] == "pass" for item in evidence["runtime_checks"].values()))
        self.assertIn('"type": "tool_call"', evidence["runtime_checks"][RUNNER.PUSH_PROBE]["subprocess"]["stderr"])
        doctor_records = evidence["runtime_checks"][RUNNER.RELOAD_PROBE]["supporting_subprocesses"]
        self.assertEqual(len(doctor_records), 2)
        self.assertEqual(doctor_records[0]["argv"][-1], "--version")
        self.assertIn("doctor", doctor_records[1]["argv"])
        self.assertFalse((self.work / ".proptermaltwo-push-side-effect").exists())

    def test_runner_uses_global_xdg_discovery_without_config_dir_flag(self) -> None:
        ambient = {"OPENAI_API_KEY": "must-not-leak", "ANTHROPIC_API_KEY": "must-not-leak", "CLAUDE_HOME": "/private/live"}
        with mock.patch.dict(os.environ, ambient):
            self.assertEqual(RUNNER.main(self.argv()), 0)
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertTrue(calls)
        for call in calls:
            self.assertNotIn("--config-dir", call["argv"])
            self.assertEqual(call["home"], str(self.home))
            self.assertEqual(call["config"], str(self.config.parent))
            self.assertEqual(call["data"], str(self.data))
            self.assertEqual(call["auth"], str(self.auth))
            self.assertEqual(call["sessions"], str(self.sessions))
            self.assertEqual(call["logs"], str(self.logs))
            self.assertIsNone(call["openai"])
            self.assertIsNone(call["anthropic"])
            self.assertIsNone(call["claude_home"])
        validator_calls = [call["argv"] for call in calls if "validate" in call["argv"]]
        self.assertEqual(validator_calls, [["validate", "skill", str(path)] for path in self.skills])
        self.assertTrue(all("--print-session-logs" in call["argv"] for call in calls if "exec" in call["argv"]))

    def test_model_prose_cannot_substitute_for_missing_trace(self) -> None:
        push_marker = self.work / ".proptermaltwo-push-side-effect"
        command = "git push --dry-run; false"
        events = [
            {"type": "tool_call", "call_id": "push", "name": "shell_exec", "input": {"command": command}},
            {"timestamp": "x", "fields": {"event": "tool_call.denied", "tool_name": "shell_exec", "call_id": "push", "blocked_by_hook": RUNNER.PUSH_HOOK}},
            {"type": "tool_result", "call_id": "push", "is_error": True},
        ]
        record = {
            "argv": ["polytoken", "exec", "--print-session-logs"],
            "returncode": 0,
            "stdout": "MODEL PROSE CLAIMS EVERYTHING PASSED\n",
            "stderr": "\n".join(json.dumps(event) for event in events),
        }
        result, _ = RUNNER.runtime_result(RUNNER.PUSH_PROBE, record, {"push_command": command, "push_marker": push_marker})
        self.assertEqual(result, "fail")

    def test_runner_requires_explicit_isolated_paths_and_refuses_bad_config_binding(self) -> None:
        args = self.argv()
        index = args.index("--config") + 1
        args[index] = str(self.base / "wrong-hooks.json")
        self.assertEqual(RUNNER.main(args), 2)
        self.assertFalse(self.evidence.exists())


if __name__ == "__main__":
    unittest.main()
