#!/usr/bin/env python3
"""ADR-22 shadow scorer and non-structural workset gates."""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

D = Path(__file__).resolve().parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, D / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


jev = load("jev_reconciliation", "jev_reconciliation.py")
builder = load("jev_workset_builder", "build-integration-workset.py")
sharder = load("jev_integration_sharder", "shard-integration.py")
evaluation = load("jev_reconciliation_eval", "jev-reconciliation-eval.py")


class JevReconciliationTests(unittest.TestCase):
    def test_model_can_be_configured_without_a_published_private_pin(self):
        env = dict(os.environ)
        env["ANGEL_JEV_MODEL"] = "jev-fixture-model"
        result = subprocess.run(
            [sys.executable, "-c", "import jev_reconciliation; print(jev_reconciliation.MODEL)"],
            cwd=D, env=env, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "jev-fixture-model")

    def make_run(self, root, eligibility=None, first_description="First mechanism.",
                 second_description="Second mechanism.", name="20260917T120000Z-jev"):
        run = root / name
        (run / "passes").mkdir(parents=True)
        finding = (
            "## Adversarial Review\n\n### Findings\n\n#### Important\n"
            "- **Same coordinate** `[moderate]` — `src/a.py:10` — {description}\n"
        )
        (run / "passes" / "adv-p1.md").write_text(
            finding.format(description=first_description))
        (run / "passes" / "adv-p2.md").write_text(
            finding.format(description=second_description))
        meta = {
            "version": 1,
            "integration_pipeline": "semantic-reducer-v1",
            "status": "ready",
            "run_dir": str(run),
            "project": "synthetic-demo",
            "date": "2026-09-17",
            "mode": "diff",
            "reader_mode": "off",
            "files_reviewed": 1,
            "preflight": {"test": "pass", "build": "pass", "lint": "pass"},
            "multiball": 2,
            "pass_denominators": {"adv": 2},
            "personas_run": ["adv"],
            "personas_dropped": [],
            "personas_failed": [],
            "codebase": {"files": 1, "lines": 20},
            "jev_eligibility": eligibility,
        }
        (run / "run-meta.json").write_text(json.dumps(meta))
        return run

    def fake_client(self, root, score=0.91):
        path = root / "fake-jev.py"
        path.write_text(
            "#!/usr/bin/env python3\n"
            "import hashlib,json,os,sys\n"
            "from pathlib import Path\n"
            "args=sys.argv[1:]\n"
            "inp=Path(args[args.index('--input')+1])\n"
            "out=Path(args[args.index('--output')+1])\n"
            "request=json.loads(inp.read_text())\n"
            "(Path(__file__).parent/'called').write_text('yes')\n"
            "(Path(__file__).parent/'request.json').write_text(json.dumps(request))\n"
            f"answers={{k:{{'noul':{score!r}}} for k in request['questions']}}\n"
            "model=os.environ.get('ANGEL_JEV_MODEL','jev-default')\n"
            "body={'state':request['state'],'questions':request['questions'],'model':model}\n"
            "request_hash=hashlib.sha256(json.dumps(body,separators=(',',':'),"
            "ensure_ascii=False).encode()).hexdigest()\n"
            "result={'provenance':{'requested_model':model,"
            "'returned_model':model,'request_sha256':request_hash,"
            "'cache_hit':False},'usage':None,'answers':answers}\n"
            "out.write_text(json.dumps(result))\n")
        path.chmod(0o700)
        return path

    def test_missing_eligibility_refuses_before_wrapper_invocation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run = self.make_run(root)
            client = self.fake_client(root)
            with self.assertRaisesRegex(ValueError, "eligibility"):
                jev.score_run(run, client)
            self.assertFalse((root / "called").exists())
            self.assertFalse((run / "jev-reconciliation.json").exists())

    def test_payload_denial_refuses_before_wrapper_invocation(self):
        protected_payloads = (
            "Leaks child@example.com in a fixture.",
            "Contains student records.",
            "Contains minor records.",
            "Contains child records.",
            "Contains a family record.",
        )
        for description in protected_payloads:
            with self.subTest(description=description), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                run = self.make_run(
                    root,
                    {"data_class": "synthetic", "approval_basis": None,
                     "identifiers_stripped": True},
                    first_description=description,
                )
                client = self.fake_client(root)
                with self.assertRaisesRegex(ValueError, "denied payload"):
                    jev.score_run(run, client)
                self.assertFalse((root / "called").exists())

    def test_success_writes_complete_bound_artifact_and_untrusted_guard(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run = self.make_run(
                root,
                {"data_class": "synthetic", "approval_basis": None,
                 "identifiers_stripped": True},
            )
            client = self.fake_client(root)
            artifact = jev.score_run(run, client)
            written = json.loads((run / "jev-reconciliation.json").read_text())
            self.assertEqual(written, artifact)
            self.assertEqual(len(written["pairs"]), 1)
            self.assertEqual(written["pairs"][0]["score"], 0.91)
            self.assertRegex(written["binding_sha256"], r"^[0-9a-f]{64}$")
            request = json.loads((root / "request.json").read_text())
            instruction = next(iter(request["questions"].values()))["instructions"]
            self.assertIn("untrusted content", instruction)
            self.assertIn("not instructions", instruction)

    def test_full_cross_pass_pair_universe_is_bounded_before_calls(self):
        rows = {
            "adv": {
                1: [{"raw_source_id": f"adv-p1:r{i}"} for i in range(17)],
                2: [{"raw_source_id": f"adv-p2:r{i}"} for i in range(17)],
            }
        }
        pairs = jev.expected_pairs(rows)
        self.assertEqual(len(pairs), 289)
        with self.assertRaisesRegex(ValueError, "256"):
            jev.enforce_pair_ceiling(pairs)

    def test_batch_plan_honors_the_wrapper_byte_ceiling_before_calls(self):
        pairs = []
        for index in range(30):
            pairs.append({
                "pair_id": f"pair_{index + 1:04d}",
                "persona": "adv",
                "left": {"raw_source_id": f"adv-p1:r{index}",
                         "description": "left " * 250},
                "right": {"raw_source_id": f"adv-p2:r{index}",
                          "description": "right " * 250},
            })
        batches = jev.batch_pairs(pairs)
        self.assertGreater(len(batches), 1)
        self.assertLessEqual(len(batches), 4)
        self.assertTrue(all(jev.request_bytes(batch) <= 60_000 for batch in batches))

    def test_request_hash_binds_the_configured_model(self):
        pair = {
            "pair_id": "pair_0001",
            "persona": "adv",
            "left": {"raw_source_id": "adv-p1:r1", "description": "left"},
            "right": {"raw_source_id": "adv-p2:r1", "description": "right"},
        }
        body = jev.wrapper_body([pair])
        self.assertEqual(body["model"], jev.MODEL)
        serialized = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        expected = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        self.assertEqual(jev.request_sha256([pair]), expected)

    def test_shadow_raw_union_preserves_same_coordinate_variants(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run = self.make_run(
                root,
                first_description="First mechanism. Ceiling at minor.",
                second_description="Second mechanism. Ceiling at important.",
            )
            workset = builder.build(run, raw_union=True)
            self.assertEqual(len(workset["candidates"]), 2)
            self.assertEqual(
                [candidate["description"] for candidate in workset["candidates"]],
                ["First mechanism. Ceiling at minor.",
                 "Second mechanism. Ceiling at important."],
            )
            self.assertEqual(
                [candidate["severity_ceiling"]["value"]
                 for candidate in workset["candidates"]],
                ["minor", "important"],
            )
            self.assertTrue(all(len(candidate["raw_source_ids"]) == 1
                                for candidate in workset["candidates"]))

    def test_run_metadata_defaults_to_ineligible_and_public_requires_stripping(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base = [
                sys.executable, str(D / "record-run-meta.py"),
                str(root), "--mode", "diff", "--reader-mode", "off",
                "--files-reviewed", "1", "--preflight-json", "{}",
                "--personas-run", "adv", "--multiball", "2",
            ]
            (root / "run-meta.json").write_text(json.dumps({
                "integration_pipeline": "semantic-reducer-v1",
            }))
            recorded = subprocess.run(base, text=True, capture_output=True)
            self.assertEqual(recorded.returncode, 0, recorded.stderr)
            meta = json.loads((root / "run-meta.json").read_text())
            self.assertEqual(meta["jev_eligibility"]["data_class"], "ineligible")

            (root / "run-meta.json").write_text(json.dumps({
                "integration_pipeline": "semantic-reducer-v1",
            }))
            refused = subprocess.run(base + ["--jev-data-class", "public"],
                                     text=True, capture_output=True)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("--jev-identifiers-stripped", refused.stderr)

    def test_advisory_matches_never_become_structural_edges(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run = self.make_run(
                root,
                {"data_class": "synthetic", "approval_basis": None,
                 "identifiers_stripped": True},
            )
            (run / "passes" / "adv-p2.md").write_text(
                "## Adversarial Review\n\n### Findings\n\n#### Important\n"
                "- **Different defect** `[moderate]` — `src/b.py:50` — Second mechanism.\n")
            jev.score_run(run, self.fake_client(root))
            workset = builder.build(run, raw_union=True, jev_advisory_threshold=0.9)
            self.assertEqual(len(workset["advisory_matches"]), 1)
            self.assertEqual(workset["candidate_edges"], [])
            self.assertEqual(len(builder.edges(workset["candidates"])), 0)
            self.assertEqual(len(sharder.components(workset)), 2)

    def test_zero_scores_add_no_advisory_matches(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run = self.make_run(
                root,
                {"data_class": "synthetic", "approval_basis": None,
                 "identifiers_stripped": True},
            )
            jev.score_run(run, self.fake_client(root, score=0))
            assisted = builder.build(run, raw_union=True, jev_advisory_threshold=0.9)
            unassisted = builder.build(run, raw_union=True)
            self.assertEqual(assisted["advisory_matches"], [])
            self.assertEqual(assisted["candidates"], unassisted["candidates"])
            self.assertEqual(assisted["candidate_edges"], unassisted["candidate_edges"])

    def test_builder_rejects_an_artifact_after_pass_content_changes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run = self.make_run(
                root,
                {"data_class": "synthetic", "approval_basis": None,
                 "identifiers_stripped": True},
            )
            jev.score_run(run, self.fake_client(root))
            path = run / "passes" / "adv-p2.md"
            path.write_text(path.read_text().replace("Second mechanism", "Changed mechanism"))
            with self.assertRaisesRegex(ValueError, "binding"):
                builder.build(run, raw_union=True, jev_advisory_threshold=0.9)

    def test_builder_rejects_incomplete_invalid_and_unsupported_artifacts(self):
        mutations = {
            "incomplete": lambda artifact: artifact["pairs"].clear(),
            "invalid score": lambda artifact: artifact["pairs"][0].update({"score": 1.1}),
            "unsupported prompt": lambda artifact: artifact.update({"prompt_version": "old"}),
            "unsupported model": lambda artifact: artifact.update({"model": "other"}),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                run = self.make_run(
                    root,
                    {"data_class": "synthetic", "approval_basis": None,
                     "identifiers_stripped": True},
                )
                jev.score_run(run, self.fake_client(root))
                path = run / "jev-reconciliation.json"
                artifact = json.loads(path.read_text())
                mutate(artifact)
                path.write_text(json.dumps(artifact))
                with self.assertRaises(ValueError):
                    builder.build(run, raw_union=True, jev_advisory_threshold=0.9)

    def test_n3_refuses_before_wrapper_invocation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run = self.make_run(
                root,
                {"data_class": "synthetic", "approval_basis": None,
                 "identifiers_stripped": True},
            )
            meta_path = run / "run-meta.json"
            meta = json.loads(meta_path.read_text())
            meta["multiball"] = 3
            meta["pass_denominators"] = {"adv": 3}
            meta_path.write_text(json.dumps(meta))
            client = self.fake_client(root)
            with self.assertRaisesRegex(ValueError, "N=2"):
                jev.score_run(run, client)
            self.assertFalse((root / "called").exists())

    def test_wrapper_failure_leaves_no_partial_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run = self.make_run(
                root,
                {"data_class": "synthetic", "approval_basis": None,
                 "identifiers_stripped": True},
            )
            client = root / "fail-jev"
            client.write_text("#!/usr/bin/env bash\nexit 7\n")
            client.chmod(0o700)
            with self.assertRaisesRegex(RuntimeError, "wrapper failed"):
                jev.score_run(run, client)
            self.assertFalse((run / "jev-reconciliation.json").exists())

    def test_sharder_transports_only_advisories_inside_the_existing_shard(self):
        workset = {
            "version": 1,
            "run": {},
            "candidates": [
                {"id": "c_adv_001", "raw_source_ids": ["a"]},
                {"id": "c_adv_002", "raw_source_ids": ["b"]},
            ],
            "candidate_edges": [],
            "advisory_matches": [{"left": "c_adv_001", "right": "c_adv_002",
                                   "score": 0.9, "source": "jev",
                                   "prompt_version": jev.PROMPT_VERSION}],
            "noise_floor_discards": [], "pass_backends": {},
            "previous_cycle": None,
        }
        together = sharder.subset(workset, workset["candidates"])
        alone = sharder.subset(workset, workset["candidates"][:1])
        self.assertEqual(len(together["advisory_matches"]), 1)
        self.assertEqual(alone["advisory_matches"], [])
        self.assertEqual(len(sharder.components(workset)), 2)

    def test_blind_five_run_calibration_freezes_the_lowest_safe_threshold(self):
        eligibility = {"data_class": "synthetic", "approval_basis": None,
                       "identifiers_stripped": True}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runs = [self.make_run(root / f"case-{index}", eligibility,
                                  name=f"20260917T12000{index}Z-jev")
                    for index in range(5)]
            labels_path = root / "private" / "labels.json"
            evaluation.prepare_calibration(runs, labels_path)
            labels = json.loads(labels_path.read_text())
            for index, (run, entry) in enumerate(zip(runs, labels["runs"])):
                duplicate = index != 0
                entry["pairs"][0]["label"] = "duplicate" if duplicate else "distinct"
                jev.score_run(run, self.fake_client(run.parent,
                                                    score=0.9 if duplicate else 0.2))
            labels_path.write_text(json.dumps(labels))
            threshold_path = root / "private" / "threshold.json"
            evaluation.freeze_threshold(labels_path, threshold_path)
            threshold = json.loads(threshold_path.read_text())
            self.assertTrue(threshold["passed"])
            self.assertGreater(threshold["attention_threshold"], 0.2)
            self.assertLess(threshold["attention_threshold"], 0.9)
            self.assertEqual(threshold["private_metrics"]["duplicate_recall"], 1.0)
            self.assertEqual(threshold_path.stat().st_mode & 0o777, 0o600)

    def test_private_eval_artifacts_cannot_be_written_into_the_skill_repo(self):
        with self.assertRaisesRegex(ValueError, "may not live"):
            evaluation.write_private(D.parent / "private-result.json", {"secret": True})

    def test_scorer_refuses_private_artifacts_inside_a_versioned_tree(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".git").mkdir()
            run = self.make_run(
                root,
                {"data_class": "synthetic", "approval_basis": None,
                 "identifiers_stripped": True},
            )
            with self.assertRaisesRegex(ValueError, "git repository"):
                jev.score_run(run, self.fake_client(root))
            self.assertFalse((run / "jev-reconciliation.json").exists())

    def test_shadow_transport_isolated_from_the_acting_report(self):
        eligibility = {"data_class": "synthetic", "approval_basis": None,
                       "identifiers_stripped": True}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run = self.make_run(root, eligibility)
            baseline_workset = builder.build(run)
            baseline_decisions = evaluation.validator.deterministic_union(
                baseline_workset, "sandbox-unavailable")
            baseline_decisions["producer"] = "reducer"
            baseline_decisions["degraded_reason"] = None
            (run / "integration-workset.json").write_text(json.dumps(baseline_workset))
            acting_path = run / "integration-decisions.json"
            acting_path.write_text(json.dumps(baseline_decisions))
            acting_before = acting_path.read_bytes()

            threshold = {
                "version": 1, "kind": "jev-reconciliation-threshold",
                "created_at": evaluation.now(), "model": jev.MODEL,
                "prompt_version": jev.PROMPT_VERSION, "cohort_sha256": "calibration",
                "cohort_size": 5, "passed": True, "attention_threshold": 0.5,
                "private_metrics": {},
            }
            threshold_path = root / "private" / "threshold.json"
            evaluation.write_private(threshold_path, threshold)
            jev.score_run(run, self.fake_client(root, score=0.9))
            ledger_path = root / "private" / "holdout.json"
            evaluation.begin_holdout(threshold_path, ledger_path)

            dispatch = root / "fake-dispatch.py"
            dispatch.write_text(
                "#!/usr/bin/env python3\n"
                "import json,sys\n"
                "from pathlib import Path\n"
                "d=Path(sys.argv[1]); w=json.loads((d/'integration-workset.json').read_text())\n"
                "findings=[]\n"
                "for i,c in enumerate(w['candidates'],1):\n"
                " findings.append({'decision_id':f'd{i}','source_candidate_ids':[c['id']],"
                "'canonical_source_id':c['id'],'title':c['title'],'summary':c['description'] or c['title'],"
                "'severity':c['severity'],'severity_reason':'source preserved','effort':c.get('effort'),"
                "'effort_reason':None,'evidence':'inference','priority_rank':i,'loop_status':None,"
                "'previous_finding_id':None,'consistency_shaped':False,'causal_claim':None,"
                "'repro_hint':None,'file':c.get('file'),'line':c.get('line'),"
                "'derived_from_candidate_ids':[]})\n"
                "dec={'version':1,'producer':'reducer','degraded_reason':None,'findings':findings,"
                "'excluded_candidates':[],'derived_records':[],'integration_notes':[],"
                "'registry_updates':[]}\n"
                "(d/'integration-decisions.json').write_text(json.dumps(dec))\n"
                "tele={'model':'fake','input_tokens':10,'output_tokens':5,'total_tokens':15,"
                "'duration_ms':7,'shards':1}\n"
                "(d/'integration-telemetry.json').write_text(json.dumps(tele))\n")
            dispatch.chmod(0o700)

            shadow = evaluation.run_shadow(
                run, threshold_path, ledger_path, dispatch=dispatch)
            self.assertEqual(acting_path.read_bytes(), acting_before)
            shadow_workset = json.loads((shadow / "integration-workset.json").read_text())
            self.assertEqual(shadow_workset["run"]["reconciliation_path"],
                             "jev-shadow-advisory")
            self.assertEqual(len(shadow_workset["advisory_matches"]), 1)
            ledger = json.loads(ledger_path.read_text())
            self.assertEqual(ledger["runs"][0]["status"], "complete")
            self.assertTrue((shadow / "jev-shadow-manifest.json").is_file())

    def test_private_holdout_evaluator_applies_all_five_promotion_clauses(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ledger = {
                "version": 1, "kind": "jev-reconciliation-holdout",
                "created_at": evaluation.now(), "model": jev.MODEL,
                "prompt_version": jev.PROMPT_VERSION, "threshold_sha256": "threshold",
                "calibration_cohort_sha256": "calibration", "target_runs": 10,
                "rubric_version": evaluation.RUBRIC_VERSION, "runs": [],
            }
            candidate = {
                "id": "c_adv_001", "persona": "adv", "severity": "important",
                "title": "Preserved mechanism", "effort": "moderate", "file": "src/a.py",
                "line": "10", "description": "The mechanism remains visible.",
                "raw_text": "The mechanism remains visible.",
                "raw_source_ids": ["adv-p1:r1"], "support_passes": ["adv-p1"],
                "severity_ceiling": {"state": "none", "value": None, "policy": None},
                "reconciliation_status": "test", "untrusted_content_flags": [],
            }
            workset = {"version": 1, "run": {}, "candidates": [candidate],
                       "candidate_edges": [], "noise_floor_discards": [],
                       "pass_backends": {}, "previous_cycle": None, "metrics": {}}
            decisions = {
                "version": 1, "producer": "reducer", "degraded_reason": None,
                "findings": [{"decision_id": "d1", "source_candidate_ids": ["c_adv_001"],
                              "canonical_source_id": "c_adv_001",
                              "title": "Preserved mechanism", "summary": "Still present.",
                              "severity": "important"}],
                "excluded_candidates": [], "derived_records": [],
                "integration_notes": [], "registry_updates": [],
            }
            for index in range(10):
                run = root / f"run-{index:02d}"
                shadow = run / evaluation.SHADOW_DIRNAME
                shadow.mkdir(parents=True)
                (run / "integration-workset.json").write_text(json.dumps(workset))
                (run / "integration-decisions.json").write_text(json.dumps(decisions))
                (shadow / "integration-workset.json").write_text(json.dumps(workset))
                (shadow / "integration-decisions.json").write_text(json.dumps(decisions))
                (run / "jev-reconciliation.json").write_text(json.dumps({
                    "elapsed_ms": 5,
                    "batches": [{"usage": {"input_tokens": 5, "output_tokens": 5}}],
                }))
                (run / "integration-telemetry.json").write_text(json.dumps({
                    "input_tokens": 80, "output_tokens": 20, "total_tokens": 100,
                    "duration_ms": 10, "shards": 1,
                }))
                (shadow / "integration-telemetry.json").write_text(json.dumps({
                    "input_tokens": 15, "output_tokens": 5, "total_tokens": 20,
                    "duration_ms": 5, "shards": 1,
                }))
                (run / "usage.jsonl").write_text(
                    json.dumps({"phase": "reconciler", "total_tokens": 100,
                                "started_at": "2026-09-19T12:00:00Z",
                                "ended_at": "2026-09-19T12:00:01Z", "duration_ms": 1000}) + "\n" +
                    json.dumps({"phase": "integrator", "total_tokens": 100,
                                "started_at": None, "ended_at": "2026-09-19T12:00:02Z",
                                "duration_ms": 1000}) + "\n")
                ledger["runs"].append({"run_dir": str(run), "shadow_dir": str(shadow),
                                       "status": "complete"})

            ledger_path = root / "private" / "ledger.json"
            evaluation.write_private(ledger_path, ledger)
            labels_path = root / "private" / "adjudication.json"
            evaluation.prepare_adjudication(ledger_path, labels_path)
            labels = json.loads(labels_path.read_text())
            for row in labels["presence"]:
                row["label"] = "present"
            for row in labels["merges"]:
                row["label"] = "same-mechanism"
            labels_path.write_text(json.dumps(labels))
            result_path = root / "private" / "result.json"
            evaluation.evaluate_holdout(ledger_path, labels_path, result_path)
            result = json.loads(result_path.read_text())
            self.assertTrue(result["passed"])
            self.assertTrue(all(result["clauses"].values()))


if __name__ == "__main__":
    unittest.main()
