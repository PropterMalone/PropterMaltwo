from __future__ import annotations

import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "manifests/hosts-v1.json").read_text(encoding="utf-8"))
README = (ROOT / "README.md").read_text(encoding="utf-8")
LEDGER = (ROOT / "docs/portability-admission.md").read_text(encoding="utf-8")
HOST_DOCS = {
    host: (ROOT / "docs/hosts" / f"{host}.md").read_text(encoding="utf-8")
    for host in ("claude-code", "codex", "polytoken", "copilot")
}
ADHD_COMPANION = (ROOT / "docs/adhd-and-agentic-work.md").read_text(encoding="utf-8")
CONNECTED_WORK = (ROOT / "docs/connected-work.md").read_text(encoding="utf-8")
START_HERE = (ROOT / "docs/start-here.md").read_text(encoding="utf-8")

LABELS = {
    "claude-code": "Claude Code/full",
    "codex-core": "Codex/core",
    "codex-standard": "Codex/standard/full",
    "polytoken-core": "Polytoken/core",
    "polytoken-standard": "Polytoken/standard/full",
    "copilot": "Copilot/core preview",
}


def table_row(text: str, label: str) -> list[str]:
    match = re.search(rf"^\| {re.escape(label)} \|(.+)$", text, re.MULTILINE)
    if not match:
        raise AssertionError(f"missing table row {label!r}")
    return [cell.strip() for cell in match.group(1).split("|") if cell.strip()]


class PortabilityAdmissionConsistency(unittest.TestCase):
    def test_readme_and_ledger_capabilities_match_manifest(self) -> None:
        cases = {
            "claude-code": MANIFEST["hosts"]["claude-code"]["profiles"]["full"]["capabilities"],
            "codex-core": MANIFEST["hosts"]["codex"]["profiles"]["core"]["capabilities"],
            "codex-standard": MANIFEST["hosts"]["codex"]["profiles"]["standard"]["capabilities"],
            "polytoken-core": MANIFEST["hosts"]["polytoken"]["profiles"]["core"]["capabilities"],
            "polytoken-standard": MANIFEST["hosts"]["polytoken"]["profiles"]["standard"]["capabilities"],
            "copilot": MANIFEST["hosts"]["copilot"]["profiles"]["core"]["capabilities"],
        }
        keys = MANIFEST["capability_keys"]
        for case, capabilities in cases.items():
            expected = [capabilities[key] for key in keys]
            for document_name, document in (("README", README), ("ledger", LEDGER)):
                with self.subTest(case=case, document=document_name):
                    self.assertEqual(table_row(document, LABELS[case]), expected)

    def test_host_maturity_and_profiles_match_manifest(self) -> None:
        for host, contract in MANIFEST["hosts"].items():
            doc = HOST_DOCS[host]
            with self.subTest(host=host):
                self.assertIn(f"**{contract['maturity']}**", doc)
                for profile in contract["supported_profiles"]:
                    self.assertRegex(doc, rf"\b{re.escape(profile)}\b")
        self.assertNotIn("Copilot is **first-class**", README)
        self.assertRegex(README, r"\*\*GitHub Copilot preview\*\*|\*\*Copilot preview\*\*")
        self.assertIn("**preview**", HOST_DOCS["copilot"])

    def test_documented_install_commands_match_accepted_combinations(self) -> None:
        expected = (
            "./install.sh --host claude-code --profile full",
            "./install.sh --host codex --profile standard",
            "./install.sh --host polytoken --profile standard",
            "./install.sh --host copilot --profile core --project /path/to/project",
        )
        combined = README + "\n" + "\n".join(HOST_DOCS.values())
        for command in expected:
            with self.subTest(command=command):
                self.assertIn(command, combined)
        self.assertIn("`--host all` accepts no profile or project", README)
        self.assertIn("excludes Copilot", README)

    def test_each_host_doc_has_merge_verify_gaps_and_rollback(self) -> None:
        for host, doc in HOST_DOCS.items():
            lower = doc.lower()
            with self.subTest(host=host):
                for concept in ("merge", "verify", "gap", "rollback", "uninstall", "--doctor", "--uninstall"):
                    self.assertIn(concept, lower)

    def test_activation_is_separate_and_no_skip_becomes_active(self) -> None:
        for document_name, document in {
            "README": README,
            "ledger": LEDGER,
            "codex": HOST_DOCS["codex"],
            "polytoken": HOST_DOCS["polytoken"],
        }.items():
            with self.subTest(document=document_name):
                self.assertIn("verified-active", document)
        self.assertIn("A skip remains `unverified`", HOST_DOCS["polytoken"])
        self.assertIn("Installed configuration alone is not", LEDGER)
        self.assertIn("not cryptographic attestation", LEDGER)
        self.assertIn("not cryptographic remote", HOST_DOCS["polytoken"])

    def test_skill_allowlists_and_full_equality_match_manifest(self) -> None:
        for host in ("codex", "polytoken"):
            profiles = MANIFEST["hosts"][host]["profiles"]
            self.assertEqual(profiles["standard"], profiles["full"])
            self.assertEqual(profiles["core"]["skills"], ["code", "status"])
            self.assertEqual(
                profiles["standard"]["skills"],
                ["code", "status", "kickoff", "wrap"],
            )
            doc = HOST_DOCS[host]
            for skill in profiles["standard"]["skills"]:
                self.assertIn(f"`{skill}`", doc)
        self.assertIn("`code,status,kickoff,wrap`", LEDGER)

    def test_memory_and_integrations_docs_have_host_boundaries(self) -> None:
        memory = (ROOT / "docs/memory-system.md").read_text(encoding="utf-8")
        integrations = (ROOT / "docs/integrations.md").read_text(encoding="utf-8")
        for host in ("Claude Code", "Codex", "Polytoken", "Copilot"):
            self.assertIn(host, memory)
            self.assertIn(host, integrations)
        self.assertIn("PROPTERMALTWO_MEMORY_DIR", memory)
        self.assertIn("do **not** infer or depend on that Claude path", memory)
        self.assertIn("not dependencies of the portable", integrations)
        self.assertIn("No Codex or Polytoken workflow calls Claude Code", integrations)

    def test_adhd_companion_is_personal_honest_and_discoverable(self) -> None:
        companion = " ".join(
            re.sub(r"(?m)^> ?", "", ADHD_COMPANION).split()
        ).lower()
        connected = " ".join(CONNECTED_WORK.split()).lower()
        self.assertIn("docs/adhd-and-agentic-work.md", README)
        self.assertIn("docs/connected-work.md", README)
        self.assertIn("i built proptermaltwo to help myself work better", companion)
        self.assertIn("not medical advice", companion)
        self.assertIn("design goals, not controlled findings", companion)
        self.assertIn("several email accounts", companion)
        self.assertIn("bluesky dms, slack, teams chats", companion)
        self.assertIn("not a bundled proptermaltwo capability", connected)
        self.assertIn("[integrations](integrations.md)", connected)

    def test_connected_work_preserves_authority_consent_and_retention_boundaries(self) -> None:
        connected = " ".join(CONNECTED_WORK.split()).lower()
        for phrase in (
            "universal keyboard",
            "per-project cursor",
            "treat inbound content as untrusted",
            "draft-first",
            "explicit action-specific approval",
            "source ids/links and timestamps",
            "fail visibly",
            "global attention view",
            "project view",
            "views' review state separate",
            "which accounts and channels were checked",
            "route attention before content",
            "automate this ladder; do not make the user operate it",
            "scheduled or event-driven supervisor",
            "never silently fall through to a less private rung",
            "machine-readable coverage ledger",
            "do not clear that exception merely because a later request succeeds",
            "cursor-contiguous replay or reconciliation",
            "explicit unresolved-gap marker",
            "healthy current check and complete outage recovery are separate states",
            "attachment stripping does not by itself make forwarding safe",
            "metadata-only",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, connected)
        for phrase in (
            "consent",
            "automate the approved meeting policy",
            "automation executes the approved policy; it does not create permission",
            "visible coverage failure",
            "offer a real alternative",
            "if recording is unavailable or declined",
            "retention period",
            "access-controlled location",
            "sensitive personal information",
            "mishearing and speaker errors are common",
            "not consent to train a model, clone a voice, or infer sensitive traits",
            "not legal advice",
        ):
            with self.subTest(meeting_phrase=phrase):
                self.assertIn(phrase, connected)

    def test_start_here_offers_skinny_path_without_installer(self) -> None:
        skinny = " ".join(re.sub(r"(?m)^> ?", "", START_HERE).split()).lower()
        self.assertIn("docs/start-here.md", README)
        self.assertIn("most of the value transfers without installing anything", " ".join(README.split()).lower())
        for phrase in (
            "memory lives outside the chat",
            "two rituals bound every session",
            "actions have boundaries",
            "chat context is disposable; continuity is durable",
            "memory-system.md",
            "adhd-and-agentic-work.md",
            "connected-work.md",
            "without running the",
            "the template's auto-load wording describes claude code",
            "proptermaltwo_memory_dir",
            "the four rules do not carry the action boundary",
            "require my explicit, action-specific authorization first",
            "never overwrite an earlier handoff",
            "do not commit, push, publish, send, delete, or discard anything",
            "the installer is not the product",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, skinny)
        for relpath in (
            "rules/quality.md",
            "rules/testing.md",
            "rules/glossary.md",
            "rules/comms.md",
            "templates/MEMORY.md",
        ):
            with self.subTest(copyable_path=relpath):
                self.assertTrue((ROOT / relpath).is_file())
                self.assertIn(relpath.lower(), skinny)

    def test_claude_first_class_is_grandfathered_honestly(self) -> None:
        for document_name, document in (
            ("README", README),
            ("ledger", LEDGER),
            ("claude-code", HOST_DOCS["claude-code"]),
        ):
            with self.subTest(document=document_name):
                self.assertIn("grandfather", document.lower())
                self.assertIn("contract evidence, not", document.lower())
        self.assertIn("doctor is a presentation layer, not a trust root", " ".join(LEDGER.split()).lower())

    def test_portability_adr_is_active_and_falsifiable(self) -> None:
        adr = ROOT / "docs/decisions/01-portable-core-thin-host-adapters.md"
        text = adr.read_text(encoding="utf-8")
        self.assertIn("status: active", text)
        self.assertIn("python3 -m unittest tests.test_adapter_contracts -v", text)
        self.assertIn(
            "python3 -m unittest tests.test_portability_adr_admission_consistency -v",
            text,
        )
        for heading in (
            "**Decision**:",
            "**Why**:",
            "**Rejected alternative**:",
            "**Could-be-wrong-if**:",
            "**Evaluated by**:",
            "**Status quo check**:",
            "**How to apply**:",
        ):
            self.assertIn(heading, text)

    def test_docs_do_not_publish_private_machine_paths(self) -> None:
        documents = [README, LEDGER, *HOST_DOCS.values()]
        for path in (ROOT / "docs").glob("*.md"):
            documents.append(path.read_text(encoding="utf-8"))
        private_path_patterns = (
            re.compile(r"/(?:home|Users)/[^/<\s]+/(?:Projects|projects)/"),
            re.compile(r"[A-Za-z]:\\Users\\[^\\<\s]+\\"),
        )
        for index, document in enumerate(documents):
            with self.subTest(document=index):
                for pattern in private_path_patterns:
                    self.assertIsNone(pattern.search(document))


if __name__ == "__main__":
    unittest.main()
