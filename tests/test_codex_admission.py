from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "scripts/codex_admission.py"
SPEC = importlib.util.spec_from_file_location("codex_admission", RUNNER_PATH)
assert SPEC and SPEC.loader
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class CodexAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.home = self.mkdir("home")
        self.codex = self.mkdir("codex")
        self.skills_home = self.mkdir("home/.agents/skills")
        self.work = self.mkdir("work")
        self.mkdir("work/.git")
        self.evidence = self.base / "evidence/codex.json"
        self.activation = self.base / "state/activation-v1.json"
        self.machine_id = self.write("machine-id", "fake machine\n")
        self.config = self.write("codex/hooks.json", "{\"hooks\":{}}\n")
        self.instruction = self.write("codex/AGENTS.md", "# PropterMaltwo global guidance for Codex\n")
        self.template = self.write("inputs/hooks.json.tmpl", "template\n")
        self.bridge = self.write("inputs/host-hook-bridge.py", "bridge\n")
        self.push = self.write("inputs/gh-identity-guard.py", "push\n")
        self.commit = self.write("inputs/gh-commit-author-guard.py", "commit\n")
        self.skills = [self.write(f"home/.agents/skills/{name}/SKILL.md", f"---\nname: {name}\ndescription: x\n---\n") for name in RUNNER.ADMITTED_SKILLS]

    def tearDown(self) -> None:
        self.temp.cleanup()

    def mkdir(self, relative: str) -> Path:
        path = self.base / relative
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write(self, relative: str, content: str) -> Path:
        path = self.base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def fake_cli(self, mode: str) -> Path:
        path = self.base / f"bin/codex-{mode}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(f"""\
            #!/usr/bin/python3
            import datetime, json, os, pathlib, sys
            mode={mode!r}; args=sys.argv[1:]
            if args == ['--version']:
                if mode == 'unavailable':
                    print('binary unavailable', file=sys.stderr); raise SystemExit(127)
                print('codex-cli 9.9.9'); raise SystemExit(0)
            home=pathlib.Path(os.environ['CODEX_HOME']); prompt=args[-1]
            session=home/'sessions/2026/09/26'; session.mkdir(parents=True,exist_ok=True)
            index=len(list(session.glob('rollout-*.jsonl')))
            rollout=session/f'rollout-{{index}}.jsonl'
            rows=[]
            def row(t,p): rows.append({{'timestamp':'x','type':t,'payload':p}})
            def emit(value): print(json.dumps(value))
            emit({{'type':'thread.started','thread_id':f't{{index}}'}}); emit({{'type':'turn.started'}})
            row('session_meta',{{'originator':'codex_exec','cli_version':'9.9.9','cwd':str(pathlib.Path.cwd())}})
            if 'Do not invoke tools' in prompt:
                skills='host_skills.instructions\\n<skills_instructions>\\n' + '\\n'.join('- '+n+': x (file: r0/'+n+'/SKILL.md)' for n in ('code','status','kickoff','wrap'))
                row('response_item',{{'type':'message','role':'developer','content':[{{'type':'input_text','text':skills}}]}})
                row('world_state',{{'state':{{'agents_md':{{'directory':str(home),'text':'# PropterMaltwo global guidance for Codex\\n'}}}}}})
            elif 'proptermaltwo-codex-benign-token' in prompt:
                token='proptermaltwo-codex-benign-token'; call='benign'
                command=prompt.split('exact command: ',1)[1].split('. Do not alter',1)[0]
                row('response_item',{{'type':'custom_tool_call','name':'exec','call_id':call,'input':'text(await tools.exec_command({{cmd:'+json.dumps(command)+',shell:"bash"}}));','status':'completed'}})
                row('response_item',{{'type':'custom_tool_call_output','call_id':call,'output':[{{'type':'input_text','text':'exit_code=0'}}]}})
                emit({{'type':'item.started','item':{{'id':'i1','type':'command_execution','command':command,'status':'in_progress'}}}})
                if mode != 'failed': pathlib.Path({str(self.work / '.proptermaltwo-codex-benign')!r}).write_text(token+'\\n')
                emit({{'type':'item.completed','item':{{'id':'i1','type':'command_execution','command':command,'status':'completed','exit_code':0}}}})
            elif 'proptermaltwo-codex-push-token' in prompt:
                token='proptermaltwo-codex-push-token'; call='push'
                command=prompt.split('exact command: ',1)[1].split('. Do not alter',1)[0]
                row('response_item',{{'type':'custom_tool_call','name':'exec','call_id':call,'input':'text(await tools.exec_command({{cmd:'+json.dumps(command)+',shell:"bash"}}));','status':'completed'}})
                if mode in ('untrusted','untrusted-silent'):
                    row('response_item',{{'type':'custom_tool_call_output','call_id':call,'output':[{{'type':'input_text','text':'exit_code=0'}}]}})
                    pathlib.Path({str(self.work / '.proptermaltwo-codex-push-side-effect')!r}).write_text('side effect\\n')
                    emit({{'type':'item.started','item':{{'id':'i2','type':'command_execution','command':command,'status':'in_progress'}}}})
                    emit({{'type':'item.completed','item':{{'id':'i2','type':'command_execution','command':command,'status':'completed','exit_code':0}}}})
                    if mode == 'untrusted': print('Hook needs review in /hooks before it can be trusted',file=sys.stderr)
                else:
                    row('response_item',{{'type':'custom_tool_call_output','call_id':call,'output':[{{'type':'input_text','text':'permissionDecisionReason: proptermaltwo-codex-pretool-deny-v1: identity guard denied push'}}]}})
            emit({{'type':'item.completed','item':{{'id':'message','type':'agent_message','text':'MODEL PROSE SAYS PASS'}}}})
            emit({{'type':'turn.completed','usage':{{}}}})
            rollout.write_text(''.join(json.dumps(x)+'\\n' for x in rows))
        """), encoding="utf-8")
        path.chmod(0o755)
        return path

    def argv(self, binary: Path) -> list[str]:
        result = [
            "--isolated-home", str(self.home), "--codex-home", str(self.codex),
            "--skills-home", str(self.skills_home), "--working-dir", str(self.work),
            "--evidence", str(self.evidence), "--config", str(self.config),
            "--instruction", str(self.instruction), "--hook-template", str(self.template),
            "--bridge", str(self.bridge), "--push-guard", str(self.push),
            "--commit-guard", str(self.commit), "--codex-bin", str(binary),
            "--machine-id", str(self.machine_id), "--activation", str(self.activation),
        ]
        for skill in self.skills:
            result.extend(("--skill-path", str(skill)))
        return result

    def test_normal_trusted_runtime_generates_pass_without_bypass(self) -> None:
        self.assertEqual(RUNNER.main(self.argv(self.fake_cli("pass"))), 0)
        evidence = json.loads(self.evidence.read_text())
        self.assertEqual(evidence["outcome"], "pass")
        self.assertEqual(evidence["activation_status"], "verified-active")
        self.assertFalse(evidence["normal_hook_trust_bypass_used"])
        self.assertEqual(evidence["sandbox_mode"], "workspace-write")
        self.assertTrue(all(item["result"] == "pass" for item in evidence["runtime_checks"].values()))
        for item in evidence["runtime_checks"].values():
            self.assertNotIn("--dangerously-bypass-hook-trust", item["subprocess"]["argv"])
            self.assertEqual(item["subprocess"]["argv"][1:4], ["exec", "--json", "-C"])
            self.assertIn("features.hooks=true", item["subprocess"]["argv"])
            self.assertTrue(item["subprocess"]["rollout_path"].startswith(str(self.codex)))
            self.assertNotIn("rollout", item["subprocess"])
        activation = json.loads(self.activation.read_text())
        self.assertEqual(activation["hosts"]["codex"]["capabilities"]["identity_hooks"]["status"], "verified-active")

    def test_normal_untrusted_runtime_is_installed_untrusted_with_hooks_remediation(self) -> None:
        self.assertEqual(RUNNER.main(self.argv(self.fake_cli("untrusted"))), 3)
        evidence = json.loads(self.evidence.read_text())
        self.assertEqual(evidence["outcome"], "installed-untrusted")
        self.assertEqual(evidence["runtime_checks"][RUNNER.PUSH]["result"], "installed-untrusted")
        activation = json.loads(self.activation.read_text())
        hook = activation["hosts"]["codex"]["capabilities"]["identity_hooks"]
        self.assertEqual(hook["status"], "installed-untrusted")
        self.assertIn("/hooks", hook["remediation"])

    def test_executed_push_without_machine_readable_warning_is_still_installed_untrusted(self) -> None:
        self.assertEqual(RUNNER.main(self.argv(self.fake_cli("untrusted-silent"))), 3)
        evidence = json.loads(self.evidence.read_text())
        self.assertEqual(evidence["outcome"], "installed-untrusted")
        self.assertIn("without a machine-readable trust warning", evidence["runtime_checks"][RUNNER.PUSH]["observation"])

    def test_unavailable_version_is_unverified_and_writes_bound_evidence(self) -> None:
        self.assertEqual(RUNNER.main(self.argv(self.fake_cli("unavailable"))), 2)
        evidence = json.loads(self.evidence.read_text())
        self.assertEqual(evidence["outcome"], "unverified")
        self.assertIsNone(evidence["codex_version"])
        self.assertEqual(evidence["runtime_checks"], {})

    def test_observed_benign_failure_is_failed(self) -> None:
        self.assertEqual(RUNNER.main(self.argv(self.fake_cli("failed"))), 1)
        evidence = json.loads(self.evidence.read_text())
        self.assertEqual(evidence["outcome"], "failed")
        self.assertEqual(evidence["runtime_checks"][RUNNER.BENIGN]["result"], "fail")

    def test_model_prose_and_missing_rollout_denial_cannot_pass(self) -> None:
        record = {
            "returncode": 0,
            "stdout": '\n'.join((
                json.dumps({"type": "thread.started", "thread_id": "x"}),
                json.dumps({"type": "turn.started"}),
                json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "PropterMaltwo denied the command"}}),
                json.dumps({"type": "turn.completed", "usage": {}}),
            )),
            "stderr": "", "rollout": "",
        }
        result, _ = RUNNER.evaluate_push(record, "printf push-token", self.work / "absent")
        self.assertEqual(result, "fail")

    def push_record(self, expected: str, *, public: str | None = None, rollout: str | None = None, output: str | None = None, output_call_id: str = "push", stderr: str = "") -> dict:
        public = expected if public is None else public
        rollout = expected if rollout is None else rollout
        output = f"permissionDecisionReason: {RUNNER.CODEX_DENY_CANARY}: denied" if output is None else output
        rows = [
            {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec", "call_id": "push", "input": f"text(await tools.exec_command({{cmd:{json.dumps(rollout)},shell:\"bash\"}}));", "status": "completed"}},
            {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": output_call_id, "output": [{"type": "input_text", "text": output}]}},
        ]
        events = [
            {"type": "thread.started", "thread_id": "x"},
            {"type": "turn.started"},
            {"type": "turn.completed", "usage": {}},
        ]
        if public:
            events.insert(2, {"type": "item.completed", "item": {"id": "p", "type": "command_execution", "command": f"/bin/bash -lc {json.dumps(public)}", "status": "completed", "exit_code": 0}})
        return {"returncode": 0, "stdout": "\n".join(json.dumps(x) for x in events), "stderr": stderr, "rollout": "\n".join(json.dumps(x) for x in rows)}

    def test_push_pass_rejects_altered_commands_generic_text_and_mismatched_call_ids(self) -> None:
        expected = "printf proptermaltwo-codex-push-token; git push --dry-run fixture"
        marker = self.work / "never-created"
        cases = (
            self.push_record(expected, public=expected + "; echo altered"),
            self.push_record(expected, rollout=expected + "; echo altered"),
            self.push_record(expected, output="identity guard said something"),
            self.push_record(expected, output=f"generic prose {RUNNER.CODEX_DENY_CANARY}"),
            self.push_record(expected, output_call_id="other"),
            self.push_record(expected, public="printf unrelated"),
        )
        for record in cases:
            with self.subTest(record=record):
                result, _ = RUNNER.evaluate_push(record, expected, marker)
                self.assertEqual(result, "fail")

    def test_canary_denial_plus_execution_and_side_effect_is_failed(self) -> None:
        expected = "printf proptermaltwo-codex-push-token; git push --dry-run fixture"
        marker = self.work / "contradictory-side-effect"
        marker.write_text("side effect\n")
        record = self.push_record(expected)
        result, _ = RUNNER.evaluate_push(record, expected, marker)
        self.assertEqual(result, "fail")

    def test_auth_error_precedes_executed_push_classification(self) -> None:
        expected = "git push --dry-run fixture"
        marker = self.work / "auth-side-effect"
        marker.write_text("side effect\n")
        record = self.push_record(expected, output="exit_code=0", stderr="401 Unauthorized")
        result, _ = RUNNER.evaluate_push(record, expected, marker)
        self.assertEqual(result, "unverified")

    def test_live_codex_home_and_bad_skill_order_are_refused(self) -> None:
        args = self.argv(self.fake_cli("pass"))
        first = args.index("--skill-path") + 1
        second = args.index("--skill-path", first) + 1
        args[first], args[second] = args[second], args[first]
        self.assertEqual(RUNNER.main(args), 2)
        self.assertFalse(self.evidence.exists())


if __name__ == "__main__":
    unittest.main()
