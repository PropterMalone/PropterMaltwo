#!/usr/bin/env python3
"""ADR-20 decision lineage, verdict, queue, and parity tests."""
import importlib.util
import unittest
from pathlib import Path

D = Path(__file__).resolve().parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, D / filename)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


validator = load("decision_validator_test", "validate-integration-decisions.py")
renderer = load("renderer_test", "render-integration.py")


def candidate(i, persona, severity="important", evidence_pass=1):
    return {"id": f"c_{persona}_{i:03d}", "persona": persona, "severity": severity,
            "title": f"Finding {i}", "effort": "moderate", "file": "src/a.py", "line": str(i),
            "description": "A concrete defect.", "raw_text": "raw", "raw_source_ids": [f"{persona}-p1:r{i}"],
            "support_passes": [f"{persona}-p{evidence_pass}"], "support_tag": None, "support_drift": None,
            "severity_ceiling": {"state": "none", "value": None, "policy": None},
            "reconciliation_status": "test"}


def decision(did, sources, canonical, rank, severity="important", evidence="inference", consistency=False):
    return {"decision_id": did, "source_candidate_ids": sources, "canonical_source_id": canonical,
            "title": did, "summary": "A final defect summary.", "severity": severity,
            "severity_reason": "source severity", "effort": "moderate", "effort_reason": None,
            "evidence": evidence, "priority_rank": rank, "loop_status": None,
            "previous_finding_id": None, "consistency_shaped": consistency,
            "causal_claim": "State changes after the deadline.", "repro_hint": "Observe state after return.",
            "file": "src/a.py", "line": str(rank), "derived_from_candidate_ids": []}


class RenderTests(unittest.TestCase):
    def setUp(self):
        cs = [candidate(1, "adv", "critical"), candidate(2, "test", "critical")]
        self.workset = {"version": 1, "run": {"integration_pipeline": "semantic-reducer-v1",
            "run_dir": "/tmp/test", "project": "demo", "date": "2026-08-30", "mode": "diff",
            "reader_mode": "off", "files_reviewed": 1, "preflight": {}, "multiball": 2,
            "pass_denominators": {"adv": 2, "test": 2}, "personas_run": ["adv", "test"],
            "personas_dropped": [], "personas_failed": [], "codebase": {"files": 1, "lines": 10}},
            "candidates": cs, "candidate_edges": [], "noise_floor_discards": [],
            "pass_backends": {}, "previous_cycle": None, "metrics": {}}
        self.decisions = {"version": 1, "producer": "reducer", "degraded_reason": None,
            "findings": [decision("merged", [cs[0]["id"], cs[1]["id"]], cs[0]["id"], 1,
                                  severity="critical")], "excluded_candidates": [],
            "derived_records": [], "integration_notes": [], "registry_updates": []}

    def test_anchored_verdict_and_queue(self):
        self.assertEqual(validator.validate(self.workset, self.decisions), [])
        snapshot, _ = renderer.build_artifacts(self.workset, self.decisions, Path("/tmp"))
        self.assertEqual(snapshot["verdict"], "CHANGES REQUIRED")
        self.assertEqual(len(snapshot["verify_queue"]), 1)
        self.assertEqual(snapshot["findings"][0]["decision_support"], {"adv": [1, 2], "test": [1, 2]})

    def test_duplicate_primary_source_rejected(self):
        extra = decision("duplicate", ["c_adv_001"], "c_adv_001", 2)
        self.decisions["findings"].append(extra)
        self.assertTrue(any("already used" in x for x in validator.validate(self.workset, self.decisions)))

    def test_union_is_schema_valid_and_visible(self):
        union = validator.deterministic_union(self.workset, "no-qualified-runner")
        self.assertEqual(validator.validate(self.workset, union), [])
        snapshot, _ = renderer.build_artifacts(self.workset, union, Path("/tmp"))
        self.assertTrue(snapshot["integration_degraded"])

    def test_degraded_report_is_bounded_and_renders_legacy_skip_shape(self):
        bounded_workset = dict(self.workset)
        bounded_workset["candidates"] = [
            candidate(i, "adv", "critical" if i == 1 else "important")
            for i in range(1, 8)
        ]
        union = validator.deterministic_union(bounded_workset, "no-qualified-runner")
        snapshot, _ = renderer.build_artifacts(bounded_workset, union, Path("/tmp"))
        snapshot["personas_dropped"] = [
            {"perf": "no hot-path code"}, "orgpolicy", {"name": "pii"}, None, ""]
        report = renderer.render_report(snapshot)
        self.assertIn("perf (no hot-path code)", report)
        self.assertIn("orgpolicy (reason not recorded)", report)
        self.assertIn("pii (reason not recorded)", report)
        self.assertIn("unknown entry 4 (reason not recorded)", report)
        self.assertNotIn("None (None)", report)
        self.assertIn("## Full candidate ledger", report)
        self.assertIn("Ledger size: 7 candidates", report)
        self.assertEqual(len(snapshot["findings"]), 7)
        self.assertIn("Finding 5", report)
        self.assertNotIn("Finding 6", report)
        self.assertNotIn("Finding 7", report)
        self.assertNotIn("## Critical", report)
        self.assertNotIn("## Important", report)


if __name__ == "__main__": unittest.main()
