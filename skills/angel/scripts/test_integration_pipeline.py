#!/usr/bin/env python3
"""End-to-end reducer-era fallback pipeline test; never calls a model."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

D = Path(__file__).resolve().parent


class PipelineTests(unittest.TestCase):
    def test_help_is_handled_before_run_path_resolution(self):
        result = subprocess.run([str(D / "integrate-run.sh"), "--help"],
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--clone-retry", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_unknown_action_is_rejected_before_run_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); run = self.make_run(root)
            result = subprocess.run([str(D / "integrate-run.sh"), str(run), "--bogus"],
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertIn("unknown action: --bogus", result.stderr)
            self.assertFalse((run / "integration-workset.json").exists())

    def make_run(self, root):
        run = root / "20260830T120000Z-pipe"
        (run / "findings").mkdir(parents=True)
        (run / "findings" / "adv.md").write_text(
            "## Adversarial Review\n\n### Findings\n\n#### Important\n"
            "- **Deadline leaks work** `[moderate]` — `src/a.py:10` — Work continues after return.\n"
            "\n#### Critical\n- None.\n")
        (run / "usage.jsonl").write_text(json.dumps({
            "phase": "persona", "name": "adv", "model": "test", "backend": "test",
            "total_tokens": 100, "tool_uses": 1, "duration_ms": 10,
            "started_at": "2026-08-30T12:00:00Z", "ended_at": "2026-08-30T12:00:01Z",
            "reader_pack": False}) + "\n")
        (run / "PROJECT_COMMIT").write_text("null\n")
        meta = {"version": 1, "integration_pipeline": "semantic-reducer-v1", "status": "ready",
                "run_dir": str(run), "project_dir": str(root), "project": "demo",
                "date": "2026-08-30", "mode": "diff", "reader_mode": "off",
                "files_reviewed": 1, "preflight": {"test": "pass", "build": "pass", "lint": "pass"},
                "multiball": None, "pass_denominators": {}, "personas_run": ["adv"],
                "personas_dropped": [], "personas_failed": [],
                "codebase": {"files": 1, "lines": 20}, "previous_run_dir": None}
        (run / "run-meta.json").write_text(json.dumps(meta))
        return run

    def make_fake_codex(self, root):
        home = root / "home"
        binary = home / ".codex" / "bin" / "codex"
        binary.parent.mkdir(parents=True)
        binary.write_text("""#!/usr/bin/python3
import json,sys
from pathlib import Path
args=sys.argv[1:]
if args == ['--version']:
    print('codex-cli 0.155.1')
elif args == ['login','status']:
    print('Logged in using ChatGPT')
elif args and args[0] == 'exec':
    output=Path(args[args.index('--output-last-message')+1])
    decision={'version':1,'producer':'reducer','degraded_reason':None,
      'findings':[{'decision_id':'d1','source_candidate_ids':['c_adv_001'],
        'canonical_source_id':'c_adv_001','title':'Deadline leaks work',
        'summary':'Work continues after the deadline returns.','severity':'important',
        'severity_reason':'source severity','effort':'moderate','effort_reason':None,
        'evidence':'code-site','priority_rank':1,'loop_status':None,
        'previous_finding_id':None,'consistency_shaped':False,
        'causal_claim':'Work survives the deadline.','repro_hint':'Observe state after return.',
        'file':'src/a.py','line':'10','derived_from_candidate_ids':[]}],
      'excluded_candidates':[],'derived_records':[],'integration_notes':[],
      'registry_updates':[]}
    output.write_text(json.dumps(decision))
    print(json.dumps({'type':'thread.started','thread_id':'fake'}))
    print(json.dumps({'type':'turn.started'}))
    print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'{}'}}))
    print(json.dumps({'type':'turn.completed','usage':{'input_tokens':12,'output_tokens':3}}))
else:
    print('unexpected fake codex invocation: '+repr(args),file=sys.stderr)
    raise SystemExit(2)
""")
        binary.chmod(0o755)
        env = os.environ.copy()
        env.update({"HOME": str(home), "PATH": f"{binary.parent}:/usr/bin:/bin",
                    "ANGEL_RUNNER_QUALIFICATION": str(root / "qualification.json"),
                    "ANGEL_USAGE_LOG": str(root / "usage.log"),
                    "ANGEL_RUNS_ROOT": str(root)})
        return binary, env

    def qualification(self, root, env):
        description_result = subprocess.run(
            [sys.executable, str(D / "run-reducer-sandbox.py"), "--describe-backend"],
            env=env, text=True, capture_output=True, timeout=10)
        self.assertEqual(description_result.returncode, 0, description_result.stderr)
        description = json.loads(description_result.stdout)
        fingerprint = subprocess.run(
            [sys.executable, str(D / "runner-fingerprint.py")], text=True,
            capture_output=True, timeout=10, check=True).stdout.strip()
        return {"version": 3, "qualified": True, "model": description["model"],
                "auth": "chatgpt", "runner_fingerprint": fingerprint,
                "runner_backend": description["backend"],
                "runner_identity": description["identity"], "checks": {}}

    def install_python_failure_wrapper(self, root, env, target, exit_code):
        wrapper_dir = root / "wrapper-bin"; wrapper_dir.mkdir()
        wrapper = wrapper_dir / "python3"
        marker = root / "intercepted-calls"
        wrapper.write_text(f"""#!/bin/sh
if [ "$1" = "{target}" ]; then
  case " $* " in
    *" --describe-backend "*) ;;
    *) printf 'intercepted\\n' >> "$FAKE_FAILURE_MARKER"; exit {exit_code} ;;
  esac
fi
exec /usr/bin/python3 "$@"
""")
        wrapper.chmod(0o755)
        env = dict(env)
        env["PATH"] = f"{wrapper_dir}:{env['PATH']}"
        env["FAKE_FAILURE_MARKER"] = str(marker)
        return env, marker

    def build_workset(self, run, env):
        result = subprocess.run(
            [sys.executable, str(D / "build-integration-workset.py"), str(run)],
            env=env, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_no_qualified_runner_renders_and_finalizes_visible_union(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); run = self.make_run(root)
            env = os.environ.copy()
            env["ANGEL_REDUCER_BACKEND"] = "disabled"
            env["ANGEL_USAGE_LOG"] = str(root / "usage.log")
            env["ANGEL_RUNS_ROOT"] = str(root)
            result = subprocess.run([str(D / "integrate-run.sh"), str(run)], env=env,
                                    text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            snapshot = json.loads((run / "findings-snapshot.json").read_text())
            self.assertEqual(snapshot["version"], 3)
            self.assertTrue(snapshot["integration_degraded"])
            self.assertEqual(snapshot["integration_degraded_reason"], "no-qualified-runner")
            self.assertEqual(len(snapshot["findings"]), 1)
            self.assertIn("DEGRADED INTEGRATION", (run / "report.md").read_text())
            self.assertTrue((run / "dispositions.json").is_file())

    def test_qualified_runner_completes_non_degraded_pipeline(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); run = self.make_run(root)
            _binary, env = self.make_fake_codex(root)
            qualification = self.qualification(root, env)
            Path(env["ANGEL_RUNNER_QUALIFICATION"]).write_text(json.dumps(qualification))
            result = subprocess.run([str(D / "integrate-run.sh"), str(run)], env=env,
                                    text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            snapshot = json.loads((run / "findings-snapshot.json").read_text())
            self.assertFalse(snapshot["integration_degraded"])
            self.assertEqual(snapshot["findings"][0]["title"], "Deadline leaks work")
            telemetry = json.loads((run / "integration-telemetry.json").read_text())
            self.assertEqual(telemetry["auth"], "chatgpt")
            self.assertEqual(telemetry["turn_count"], 1)

    def test_every_qualification_binding_mismatch_degrades_closed(self):
        mutations = {
            "model": "wrong-model", "auth": "api", "runner_fingerprint": "0" * 64,
            "runner_backend": "wrong-backend", "runner_identity": "wrong-identity",
        }
        for field, wrong in mutations.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as td:
                root = Path(td); run = self.make_run(root)
                _binary, env = self.make_fake_codex(root)
                qualification = self.qualification(root, env)
                qualification[field] = wrong
                Path(env["ANGEL_RUNNER_QUALIFICATION"]).write_text(json.dumps(qualification))
                result = subprocess.run([str(D / "integrate-run.sh"), str(run)], env=env,
                                        text=True, capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                snapshot = json.loads((run / "findings-snapshot.json").read_text())
                self.assertTrue(snapshot["integration_degraded"])
                self.assertEqual(snapshot["integration_degraded_reason"],
                                 "no-qualified-runner")

    def test_unsharded_cleanup_failure_maps_once_to_typed_degradation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); run = self.make_run(root)
            _binary, env = self.make_fake_codex(root)
            qualification = self.qualification(root, env)
            Path(env["ANGEL_RUNNER_QUALIFICATION"]).write_text(json.dumps(qualification))
            self.build_workset(run, env)
            env, marker = self.install_python_failure_wrapper(
                root, env, str(D / "run-reducer-sandbox.py"), 75)
            result = subprocess.run([str(D / "dispatch-integration.sh"), str(run)], env=env,
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            decisions = json.loads((run / "integration-decisions.json").read_text())
            self.assertEqual(decisions["degraded_reason"], "runner-cleanup-failed")
            self.assertEqual(marker.read_text().splitlines(), ["intercepted"])

    def test_sharded_cleanup_failure_maps_once_to_typed_degradation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); run = self.make_run(root)
            _binary, env = self.make_fake_codex(root)
            qualification = self.qualification(root, env)
            Path(env["ANGEL_RUNNER_QUALIFICATION"]).write_text(json.dumps(qualification))
            self.build_workset(run, env)
            workset_path = run / "integration-workset.json"
            workset = json.loads(workset_path.read_text())
            workset["metrics"]["tokens_estimate"] = 24001
            workset_path.write_text(json.dumps(workset))
            env, marker = self.install_python_failure_wrapper(
                root, env, str(D / "shard-integration.py"), 4)
            result = subprocess.run([str(D / "dispatch-integration.sh"), str(run)], env=env,
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            decisions = json.loads((run / "integration-decisions.json").read_text())
            self.assertEqual(decisions["degraded_reason"], "runner-cleanup-failed")
            self.assertEqual(marker.read_text().splitlines(), ["intercepted"])

    def test_clone_retry_creates_fresh_run_with_preintegration_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); run = self.make_run(root)
            env = os.environ.copy()
            env["ANGEL_REDUCER_BACKEND"] = "disabled"
            env["ANGEL_USAGE_LOG"] = str(root / "usage.log")
            env["ANGEL_RUNS_ROOT"] = str(root)
            first = subprocess.run([str(D / "integrate-run.sh"), str(run)], env=env,
                                   text=True, capture_output=True, timeout=30)
            self.assertEqual(first.returncode, 0, first.stderr)
            retry = subprocess.run([str(D / "integrate-run.sh"), str(run), "--clone-retry"],
                                   env=env, text=True, capture_output=True, timeout=30)
            self.assertEqual(retry.returncode, 0, retry.stderr)
            clones = [p for p in root.iterdir() if p.is_dir() and p != run]
            self.assertEqual(len(clones), 1)
            clone = clones[0]
            meta = json.loads((clone / "run-meta.json").read_text())
            self.assertEqual(meta["previous_run_dir"], str(run))
            self.assertTrue((clone / "findings-snapshot.json").is_file())
            phases = [json.loads(line)["phase"] for line in
                      (clone / "usage.jsonl").read_text().splitlines()]
            self.assertEqual(phases.count("persona"), 1)
            self.assertEqual(phases.count("integrator"), 1)


if __name__ == "__main__": unittest.main()
