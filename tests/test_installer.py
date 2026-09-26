from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install.sh"
MANIFEST = ROOT / "manifests/hosts-v1.json"
POLICY = ROOT / "tests/fixtures/expected_installer_policy_v1.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class InstallerCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.home = self.base / "home"
        self.claude = self.base / "claude"
        self.codex = self.base / "codex"
        self.skills = self.base / "agent-skills"
        self.polytoken = self.base / "config/polytoken"
        self.state = self.base / "data/proptermaltwo"
        self.project = self.base / "project"
        self.home.mkdir()
        self.project.mkdir()
        self.env = os.environ.copy()
        self.env.update(
            HOME=str(self.home),
            CLAUDE_HOME=str(self.claude),
            CODEX_HOME=str(self.codex),
            CODEX_SKILLS_HOME=str(self.skills),
            POLYTOKEN_HOME=str(self.polytoken),
            PROPTERMALTWO_HOME=str(self.state),
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_install(self, *args: str, check: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [str(INSTALLER), *args], cwd=ROOT, env=env or self.env,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        )
        if check and result.returncode != 0:
            self.fail(f"command failed ({result.returncode}): {args}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        return result

    def ledger(self) -> dict:
        return json.loads((self.state / "state/ledger-v1.json").read_text())


class ManifestPolicyTests(InstallerCase):
    def test_manifest_schema_paths_and_independent_policy(self) -> None:
        manifest = json.loads(MANIFEST.read_text())
        policy = json.loads(POLICY.read_text())
        for key in ("schema_version", "static_support_values", "activation_values", "capability_keys", "profile_order", "shared_groups", "hosts", "all_selection"):
            self.assertEqual(manifest[key], policy[key], key)
        self.assertEqual(manifest["omitted_skills"], policy["unadmitted_skills"])
        self.assertEqual(json.loads((ROOT / "adapters/codex/hooks.json.tmpl").read_text()), policy["hook_templates"]["codex"])
        self.assertEqual(json.loads((ROOT / "adapters/polytoken/hooks.json.tmpl").read_text()), policy["hook_templates"]["polytoken"])
        result = self.run_install("--validate-manifest")
        self.assertIn("Manifest valid", result.stdout)

    def test_policy_fixture_rejects_every_unaccepted_selection(self) -> None:
        policy = json.loads(POLICY.read_text())
        for case in policy["rejections"]:
            args = ["--host", case["host"]]
            if case.get("profile"):
                args.extend(("--profile", case["profile"]))
            if case.get("project"):
                args.extend(("--project", str(self.project)))
            result = self.run_install(*args, check=False)
            self.assertEqual(result.returncode, 2, (case, result.stdout, result.stderr))

    def test_policy_fixture_detects_extra_missing_or_changed_contract_fields(self) -> None:
        manifest = json.loads(MANIFEST.read_text())
        policy = json.loads(POLICY.read_text())
        mutations = (
            lambda value: value["shared_groups"]["shared_core"].append({"source": "rules/extra.md", "destination": "shared/rules/extra.md", "operation": "managed-copy"}),
            lambda value: value["hosts"]["codex"]["artifact_groups"]["codex_core"].pop(),
            lambda value: value["hosts"]["polytoken"]["profiles"]["standard"]["capabilities"].update(identity_hooks="native"),
            lambda value: value["hosts"]["copilot"]["artifact_groups"]["copilot_core"][0].update(operation="managed-copy"),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(case=index):
                changed = json.loads(json.dumps(manifest))
                mutate(changed)
                actual_contract = {key: changed[key] for key in ("shared_groups", "hosts")}
                expected_contract = {key: policy[key] for key in ("shared_groups", "hosts")}
                self.assertNotEqual(actual_contract, expected_contract)

    def test_profiles_are_monotonic_and_full_equals_standard(self) -> None:
        manifest = json.loads(MANIFEST.read_text())
        for host_id in ("codex", "polytoken"):
            host = manifest["hosts"][host_id]
            core = host["profiles"]["core"]
            standard = host["profiles"]["standard"]
            self.assertLessEqual(set(core["groups"]), set(standard["groups"]))
            self.assertLessEqual(set(core["skills"]), set(standard["skills"]))
            self.assertEqual(standard, host["profiles"]["full"])

    def test_rejected_host_profile_combinations(self) -> None:
        cases = (
            ("--host", "claude-code", "--profile", "core"),
            ("--host", "copilot", "--profile", "standard", "--project", str(self.project)),
            ("--host", "copilot"),
            ("--host", "all", "--profile", "standard"),
            ("--host", "all", "--project", str(self.project)),
        )
        for args in cases:
            with self.subTest(args=args):
                result = self.run_install(*args, check=False)
                self.assertEqual(result.returncode, 2)
                self.assertIn("ERROR:", result.stderr)

    def test_copilot_exact_policy_and_preview_label(self) -> None:
        policy = json.loads(POLICY.read_text())
        result = self.run_install("--host", "copilot", "--project", str(self.project))
        destinations = []
        for line in result.stdout.splitlines():
            if " [" in line and str(self.project) in line:
                destinations.append(str(Path(line.split()[1]).relative_to(self.project)))
        expected = [item["destination"] for item in policy["hosts"]["copilot"]["artifact_groups"]["copilot_core"]]
        self.assertEqual(sorted(destinations), sorted(expected))
        doctor = self.run_install("--host", "copilot", "--project", str(self.project), "--doctor", "--json")
        self.assertEqual(json.loads(doctor.stdout)["hosts"]["copilot"]["maturity"], "preview")


class ClaudeCharacterizationTests(InstallerCase):
    def test_legacy_default_is_claude_full_dry_run(self) -> None:
        result = self.run_install()
        self.assertIn("[claude-code:full]", result.stdout)
        self.assertIn("dry run", result.stdout)
        self.assertFalse(self.claude.exists())
        self.assertFalse(self.state.exists())

    def test_claude_full_tree_and_settings_seed(self) -> None:
        self.run_install("--apply")
        for root_name in ("CLAUDE.md", "rules", "skills", "hooks", "templates", "scripts", "docs", "statusline-command.sh", "settings.example.json"):
            source = ROOT / root_name
            if source.is_file():
                self.assertEqual(digest(source), digest(self.claude / root_name))
            else:
                for item in source.rglob("*"):
                    if item.is_file():
                        self.assertEqual(digest(item), digest(self.claude / item.relative_to(ROOT)))
        self.assertEqual(digest(ROOT / "settings.example.json"), digest(self.claude / "settings.json"))

    def test_claude_settings_seed_only_when_absent(self) -> None:
        self.claude.mkdir()
        settings = self.claude / "settings.json"
        settings.write_text('{"mine": true}\n')
        self.run_install("--apply")
        self.assertEqual(settings.read_text(), '{"mine": true}\n')

    def test_claude_executable_modes(self) -> None:
        self.run_install("--apply")
        expected_exec = [self.claude / "statusline-command.sh"]
        expected_exec.extend((self.claude / "hooks").glob("*.py"))
        for path in expected_exec:
            with self.subTest(path=path):
                self.assertTrue(path.stat().st_mode & stat.S_IXUSR)

    def test_legacy_modified_file_is_replaced_and_original_restored(self) -> None:
        self.claude.mkdir()
        target = self.claude / "CLAUDE.md"
        target.write_text("original user content\n")
        self.run_install("--apply")
        first = self.ledger()["artifacts"][str(target)]
        backup = Path(first["original"]["backup"])
        self.assertEqual(backup.read_text(), "original user content\n")
        visible = list(self.claude.glob(".propter-maltwo-backup-*/CLAUDE.md"))
        self.assertEqual(len(visible), 1)
        self.assertRegex(visible[0].parent.name, r"^\.propter-maltwo-backup-\d{8}T\d{6}$")
        self.assertEqual(visible[0].read_text(), "original user content\n")
        target.write_text("modified after install\n")
        self.run_install("--apply")
        second = self.ledger()["artifacts"][str(target)]
        self.assertEqual(second["original"]["backup"], str(backup))
        self.run_install("--uninstall", "--apply")
        self.assertEqual(target.read_text(), "original user content\n")

    def test_legacy_nested_hook_conflict_gets_visible_timestamp_backup(self) -> None:
        target = self.claude / "hooks/gh-identity-guard.py"
        target.parent.mkdir(parents=True)
        target.write_text("old hook\n")
        self.run_install("--apply")
        visible = list(self.claude.glob(".propter-maltwo-backup-*/hooks/gh-identity-guard.py"))
        self.assertEqual(len(visible), 1)
        self.assertEqual(visible[0].read_text(), "old hook\n")
        self.assertEqual(target.read_bytes(), (ROOT / "hooks/gh-identity-guard.py").read_bytes())


class LifecycleTests(InstallerCase):
    def test_apply_twice_is_idempotent(self) -> None:
        first = self.run_install("--host", "polytoken", "--profile", "core", "--apply")
        second = self.run_install("--host", "polytoken", "--profile", "core", "--apply")
        self.assertIn("Applied", first.stdout)
        self.assertIn("Applied 0 filesystem change(s)", second.stdout)

    def test_conflicting_new_host_instruction_is_staged(self) -> None:
        agents = self.polytoken / "AGENTS.md"
        agents.parent.mkdir(parents=True)
        agents.write_text("user instructions\n")
        self.run_install("--host", "polytoken", "--profile", "core", "--apply")
        self.assertEqual(agents.read_text(), "user instructions\n")
        fragment = self.polytoken / "AGENTS.md.proptermaltwo.example"
        self.assertTrue(fragment.is_file())
        self.assertIn("MERGE REQUIRED", self.run_install("--host", "polytoken", "--profile", "core", "--apply").stdout)

    def test_unmanaged_staged_fragments_are_never_overwritten(self) -> None:
        cases = (
            (self.codex / "AGENTS.md", self.codex / "AGENTS.md.proptermaltwo.example", ("--host", "codex", "--profile", "core")),
            (self.polytoken / "AGENTS.md", self.polytoken / "AGENTS.md.proptermaltwo.example", ("--host", "polytoken", "--profile", "core")),
            (self.project / ".github/copilot-instructions.md", self.project / ".github/copilot-instructions.md.proptermaltwo.example", ("--host", "copilot", "--profile", "core", "--project", str(self.project))),
        )
        for primary, fragment, args in cases:
            with self.subTest(host=args[1]):
                primary.parent.mkdir(parents=True, exist_ok=True)
                primary.write_text("user primary\n")
                fragment.write_text("user fragment\n")
                result = self.run_install(*args, "--apply", check=False)
                self.assertEqual(result.returncode, 2)
                self.assertIn("refusing to overwrite unmanaged staged fragment", result.stderr)
                self.assertEqual(primary.read_text(), "user primary\n")
                self.assertEqual(fragment.read_text(), "user fragment\n")
                primary.unlink()
                fragment.unlink()

    def test_managed_instruction_upgrade_preserves_original_uninstall_state(self) -> None:
        target = self.polytoken / "AGENTS.md"
        target.parent.mkdir(parents=True)
        target.write_text("original user instructions\n")
        self.run_install("--host", "polytoken", "--profile", "core", "--apply")
        fragment = self.polytoken / "AGENTS.md.proptermaltwo.example"
        fragment.unlink()
        target.unlink()
        target.write_text((ROOT / "adapters/polytoken/AGENTS.md").read_text().replace("# PropterMaltwo", "# Old PropterMaltwo", 1).replace("{{PROPTERMALTWO_HOME}}", str(self.state)))
        ledger_path = self.state / "state/ledger-v1.json"
        ledger = json.loads(ledger_path.read_text())
        record = ledger["artifacts"].pop(str(fragment))
        record["installed_checksum"] = digest(target)
        original_backup = self.state / "state/backups-v1/original-agents.bin"
        original_backup.parent.mkdir(parents=True, exist_ok=True)
        original_backup.write_text("original user instructions\n")
        record["operation"] = "managed-copy"
        record["canonical_source"] = "adapters/polytoken/AGENTS.md"
        record["created_by_installer"] = False
        record["original"] = {"kind": "file", "checksum": digest(original_backup), "mode": 0o644, "backup": str(original_backup)}
        ledger["artifacts"][str(target)] = record
        ledger_path.write_text(json.dumps(ledger))
        self.run_install("--host", "polytoken", "--profile", "core", "--apply")
        self.assertEqual(target.read_bytes(), (ROOT / "adapters/polytoken/AGENTS.md").read_bytes().replace(b"{{PROPTERMALTWO_HOME}}", str(self.state).encode()))
        self.run_install("--host", "polytoken", "--profile", "core", "--uninstall", "--apply")
        self.assertEqual(target.read_text(), "original user instructions\n")

    def test_modified_installed_file_survives_uninstall(self) -> None:
        self.run_install("--host", "polytoken", "--profile", "core", "--apply")
        skill = self.polytoken / "skills/code/SKILL.md"
        skill.write_text(skill.read_text() + "\nuser change\n")
        result = self.run_install("--host", "polytoken", "--profile", "core", "--uninstall", "--apply")
        self.assertTrue(skill.exists())
        self.assertIn("preserved modified managed path", result.stdout)

    def test_host_all_owner_sets_and_partial_uninstall(self) -> None:
        self.run_install("--host", "all", "--apply")
        shared = self.state / "shared/rules/quality.md"
        record = self.ledger()["artifacts"][str(shared)]
        self.assertEqual(record["owners"], ["codex", "polytoken"])
        self.run_install("--host", "codex", "--uninstall", "--apply")
        self.assertTrue(shared.exists())
        self.assertEqual(self.ledger()["artifacts"][str(shared)]["owners"], ["polytoken"])

    def test_polytoken_hooks_render_absolute_bridge_and_reapply_is_noop(self) -> None:
        first = self.run_install("--host", "polytoken", "--profile", "standard", "--apply")
        hooks_path = self.polytoken / "hooks.json"
        hooks_text = hooks_path.read_text()
        hooks = json.loads(hooks_text)
        bridge = self.state / "shared/hooks/host-hook-bridge.py"
        expected_prefix = f"python3 '{bridge}' --host polytoken --guard "
        self.assertNotIn("{{", hooks_text)
        self.assertEqual([item["handler"]["bash"] for item in hooks], [expected_prefix + "push", expected_prefix + "commit"])
        self.assertTrue(bridge.is_file())
        instructions = (self.polytoken / "AGENTS.md").read_text()
        self.assertNotIn("{{PROPTERMALTWO_HOME}}", instructions)
        self.assertIn(str(self.state / "shared/rules/quality.md"), instructions)
        self.assertIn("Applied 21 filesystem change(s)", first.stdout)
        second = self.run_install("--host", "polytoken", "--profile", "standard", "--apply")
        self.assertIn("Applied 0 filesystem change(s)", second.stdout)

    def test_polytoken_hook_bridge_path_is_posix_safely_quoted(self) -> None:
        quoted_state = self.base / "data/it's-state"
        env = dict(self.env, PROPTERMALTWO_HOME=str(quoted_state))
        self.run_install("--host", "polytoken", "--profile", "standard", "--apply", env=env)
        hooks_text = (self.polytoken / "hooks.json").read_text()
        hooks = json.loads(hooks_text)
        expected = str(quoted_state / "shared/hooks/host-hook-bridge.py").replace("'", "'\"'\"'")
        self.assertEqual(hooks[0]["handler"]["bash"], f"python3 '{expected}' --host polytoken --guard push")
        self.assertNotIn("{{", hooks_text)

    def test_managed_hook_definitions_upgrade_and_preserve_user_entries(self) -> None:
        cases = (
            ("polytoken", self.polytoken / "hooks.json", ("--host", "polytoken", "--profile", "standard")),
            ("codex", self.codex / "hooks.json", ("--host", "codex", "--profile", "standard")),
        )
        for host, hooks_path, args in cases:
            with self.subTest(host=host):
                self.run_install(*args, "--apply")
                ledger_path = self.state / "state/ledger-v1.json"
                ledger = json.loads(ledger_path.read_text())
                document = json.loads(hooks_path.read_text())
                definitions = document if host == "polytoken" else document["hooks"]["PreToolUse"]
                old = json.loads(json.dumps(definitions[0]))
                command_container = old["handler"] if host == "polytoken" else old["hooks"][0]
                command_container["bash" if host == "polytoken" else "command"] += " --old-definition"
                definitions[0] = old
                user = {"name": "user-hook", "event": "custom"} if host == "polytoken" else {"matcher": "^Other$", "hooks": [{"type": "command", "command": "true"}]}
                definitions.append(user)
                hooks_path.write_text(json.dumps(document, indent=2) + "\n")
                record = ledger["artifacts"][str(hooks_path)]
                record["installed_checksum"] = digest(hooks_path)
                record["managed_definition_hashes"] = [hashlib.sha256(json.dumps(item, sort_keys=True, separators=(",", ":")).encode()).hexdigest() for item in definitions[:-1]]
                ledger_path.write_text(json.dumps(ledger))
                self.run_install(*args, "--apply")
                upgraded = json.loads(hooks_path.read_text())
                upgraded_defs = upgraded if host == "polytoken" else upgraded["hooks"]["PreToolUse"]
                self.assertIn(user, upgraded_defs)
                self.assertNotIn("--old-definition", json.dumps(upgraded_defs))
                self.assertEqual(len(self.ledger()["artifacts"][str(hooks_path)]["managed_definition_hashes"]), 2)
                self.run_install(*args, "--uninstall", "--apply")
                self.assertFalse(hooks_path.exists())
                shutil.rmtree(self.state)
                shutil.rmtree(self.polytoken if host == "polytoken" else self.codex, ignore_errors=True)
                shutil.rmtree(self.skills, ignore_errors=True)

    def test_uninstall_restores_replaced_config(self) -> None:
        hooks = self.polytoken / "hooks.json"
        hooks.parent.mkdir(parents=True)
        hooks.write_text('[{"name":"user","event":"custom"}]\n')
        self.run_install("--host", "polytoken", "--profile", "standard", "--apply")
        installed = json.loads(hooks.read_text())
        self.assertEqual(installed[0]["name"], "user")
        self.assertGreater(len(installed), 1)
        self.run_install("--host", "polytoken", "--profile", "standard", "--uninstall", "--apply")
        self.assertEqual(json.loads(hooks.read_text()), [{"name": "user", "event": "custom"}])

    def test_failure_injection_rolls_back_and_leaves_ledger_uncommitted(self) -> None:
        env = dict(self.env, PROPTERMALTWO_FAIL_AT="after-mutation:0")
        result = self.run_install("--host", "polytoken", "--profile", "core", "--apply", check=False, env=env)
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.polytoken / "AGENTS.md").exists())
        self.assertFalse((self.state / "state/ledger-v1.json").exists())
        self.assertFalse((self.state / "state/journal-v1.json").exists())

    def test_failure_boundaries_cover_operation_classes_and_uninstall(self) -> None:
        cases = (
            (("--host", "polytoken", "--profile", "core"), "before-mutation:1"),
            (("--host", "codex", "--profile", "core"), "after-mutation:0"),
            (("--host", "polytoken", "--profile", "standard"), "before-ledger"),
        )
        for index, (args, boundary) in enumerate(cases):
            with self.subTest(host=args[1], boundary=boundary):
                root = self.base / f"failure-{index}"
                env = dict(
                    self.env,
                    HOME=str(root / "home"), CLAUDE_HOME=str(root / "claude"), CODEX_HOME=str(root / "codex"),
                    CODEX_SKILLS_HOME=str(root / "skills"), POLYTOKEN_HOME=str(root / "config/polytoken"),
                    PROPTERMALTWO_HOME=str(root / "data/proptermaltwo"), PROPTERMALTWO_FAIL_AT=boundary,
                )
                Path(env["HOME"]).mkdir(parents=True)
                result = self.run_install(*args, "--apply", check=False, env=env)
                self.assertEqual(result.returncode, 2)
                ledger_path = Path(env["PROPTERMALTWO_HOME"]) / "state/ledger-v1.json"
                if ledger_path.exists():
                    self.assertEqual(json.loads(ledger_path.read_text())["artifacts"], {})
                self.assertFalse((Path(env["PROPTERMALTWO_HOME"]) / "state/journal-v1.json").exists())
                self.assertFalse((Path(env["POLYTOKEN_HOME"]) / "AGENTS.md").exists())
                self.assertFalse((Path(env["CODEX_HOME"]) / "AGENTS.md").exists())

        self.run_install("--host", "codex", "--profile", "core", "--apply")
        before = json.loads((self.state / "state/ledger-v1.json").read_text())
        env = dict(self.env, PROPTERMALTWO_FAIL_AT="after-mutation:0")
        failed = self.run_install("--host", "codex", "--profile", "core", "--uninstall", "--apply", check=False, env=env)
        self.assertEqual(failed.returncode, 2)
        self.assertEqual(json.loads((self.state / "state/ledger-v1.json").read_text()), before)
        self.assertTrue((self.codex / "AGENTS.md").is_file())

    def test_real_sigint_at_mutation_boundary_rolls_back(self) -> None:
        env = dict(self.env, PROPTERMALTWO_SLEEP_AT="after-mutation:0", PROPTERMALTWO_SLEEP_SECONDS="30")
        process = subprocess.Popen(
            [str(INSTALLER), "--host", "polytoken", "--profile", "core", "--apply"],
            cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        journal = self.state / "state/journal-v1.json"
        deadline = time.time() + 10
        while time.time() < deadline:
            if journal.exists():
                data = json.loads(journal.read_text())
                if data.get("pending") and (self.polytoken / "AGENTS.md").exists():
                    break
            time.sleep(0.05)
        else:
            process.kill()
            self.fail("installer did not reach the after-mutation boundary")
        process.send_signal(signal.SIGINT)
        stdout, stderr = process.communicate(timeout=15)
        self.assertEqual(process.returncode, 2, (stdout, stderr))
        self.assertFalse((self.polytoken / "AGENTS.md").exists())
        self.assertFalse((self.state / "state/ledger-v1.json").exists())
        self.assertFalse(journal.exists())

    def test_rollback_failure_retains_journal_and_blocks_mutation(self) -> None:
        env = dict(
            self.env,
            PROPTERMALTWO_FAIL_AT="after-mutation:0",
            PROPTERMALTWO_ROLLBACK_FAIL_AT="0",
        )
        failed = self.run_install("--host", "polytoken", "--profile", "core", "--apply", check=False, env=env)
        self.assertEqual(failed.returncode, 2)
        self.assertIn("rollback incomplete", failed.stderr)
        journal = self.state / "state/journal-v1.json"
        self.assertTrue(journal.is_file())
        self.assertEqual(json.loads(journal.read_text())["status"], "rollback-failed")
        blocked = self.run_install("--host", "polytoken", "--profile", "core", "--apply", check=False)
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("Recovery command", blocked.stderr)
        recovered = self.run_install("--recover", "--apply")
        self.assertIn("Recovered transaction", recovered.stdout)
        self.assertFalse((self.polytoken / "AGENTS.md").exists())

    def test_recovery_restores_persisted_pending_mutation_and_ledger(self) -> None:
        self.run_install("--host", "polytoken", "--profile", "core", "--apply")
        ledger_path = self.state / "state/ledger-v1.json"
        ledger_before = json.loads(ledger_path.read_text())
        destination = self.polytoken / "AGENTS.md"
        prior_path = self.state / "state/recovery-v1/manual/00000.file"
        prior_path.parent.mkdir(parents=True)
        shutil.copy2(destination, prior_path)
        prior = {"kind": "file", "backup": str(prior_path), "mode": stat.S_IMODE(destination.stat().st_mode)}
        destination.write_text("hard-kill mutation\n")
        ledger_path.write_text(json.dumps({"schema_version": 1, "product": "PropterMaltwo", "updated_at": "bad", "artifacts": {}}))
        journal = {
            "schema_version": 1,
            "transaction_id": "pending-hard-kill",
            "status": "applying",
            "ledger_before": ledger_before,
            "completed": [],
            "pending": {"destination": str(destination), "prior": prior},
        }
        journal_path = self.state / "state/journal-v1.json"
        journal_path.write_text(json.dumps(journal))
        recovered = self.run_install("--recover", "--apply")
        self.assertIn("prior filesystem and ledger state restored", recovered.stdout)
        self.assertNotEqual(destination.read_text(), "hard-kill mutation\n")
        self.assertEqual(json.loads(ledger_path.read_text()), ledger_before)
        self.assertFalse(journal_path.exists())

    def test_recovery_finalizes_matching_committed_journal(self) -> None:
        self.run_install("--host", "polytoken", "--profile", "core", "--apply")
        ledger_path = self.state / "state/ledger-v1.json"
        ledger = json.loads(ledger_path.read_text())
        journal_path = self.state / "state/journal-v1.json"
        journal_path.write_text(json.dumps({
            "schema_version": 1,
            "transaction_id": "committed-hard-kill",
            "status": "committed",
            "ledger_before": {"schema_version": 1, "product": "PropterMaltwo", "updated_at": "old", "artifacts": {}},
            "ledger_after": ledger,
            "completed": [],
        }))
        recovered = self.run_install("--recover", "--apply")
        self.assertIn("Finalized committed transaction", recovered.stdout)
        self.assertEqual(json.loads(ledger_path.read_text()), ledger)
        self.assertTrue((self.polytoken / "AGENTS.md").is_file())
        self.assertFalse(journal_path.exists())

    def test_unresolved_journal_refuses_uninstall(self) -> None:
        self.run_install("--host", "polytoken", "--profile", "core", "--apply")
        journal = self.state / "state/journal-v1.json"
        journal.write_text(json.dumps({"schema_version": 1, "completed": [], "status": "applying"}))
        result = self.run_install("--host", "polytoken", "--profile", "core", "--uninstall", "--apply", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("unresolved transaction journal", result.stderr)
        self.assertTrue((self.polytoken / "AGENTS.md").is_file())
        recovery = f"./install.sh --recover --apply --proptermaltwo-home '{self.state}'"
        human = self.run_install("--host", "polytoken", "--profile", "core", "--doctor", check=False)
        self.assertEqual(human.returncode, 1)
        self.assertIn(recovery, human.stdout)
        machine = self.run_install("--host", "polytoken", "--profile", "core", "--doctor", "--json", check=False)
        self.assertEqual(machine.returncode, 1)
        self.assertEqual(json.loads(machine.stdout)["state"]["recovery_command"], recovery)

    def test_corrupt_ledger_refuses_mutation(self) -> None:
        ledger = self.state / "state/ledger-v1.json"
        ledger.parent.mkdir(parents=True)
        ledger.write_text("not json")
        result = self.run_install("--host", "polytoken", "--profile", "core", "--apply", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("corrupt ledger blocks mutation", result.stderr)
        self.assertFalse(self.polytoken.exists())

    def test_concurrent_lock_refuses_second_mutation(self) -> None:
        lock = self.state / "state/installer.lock"
        lock.parent.mkdir(parents=True)
        with lock.open("a+") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_install("--host", "polytoken", "--profile", "core", "--apply", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("holds lock", result.stderr)


class DoctorTests(InstallerCase):
    def test_doctor_separates_static_and_activation(self) -> None:
        result = self.run_install("--host", "polytoken", "--profile", "standard", "--doctor", "--json")
        report = json.loads(result.stdout)
        capabilities = report["hosts"]["polytoken"]["capabilities"]
        for value in capabilities.values():
            self.assertIn(value["static_support"], {"native", "adapted", "degraded", "unsupported", "not-tested"})
            self.assertIn(value["activation"]["status"], {"verified-active", "installed-untrusted", "inactive", "unverified", "failed"})
        self.assertEqual(capabilities["identity_hooks"]["static_support"], "adapted")
        self.assertEqual(capabilities["identity_hooks"]["activation"]["status"], "unverified")

    def test_active_wording_rejects_unvalidated_verified_active_label(self) -> None:
        human = self.run_install("--host", "polytoken", "--profile", "standard", "--doctor").stdout
        self.assertNotIn(" — active", human)
        activation = self.state / "state/activation-v1.json"
        activation.parent.mkdir(parents=True, exist_ok=True)
        activation.write_text(json.dumps({
            "schema_version": 1,
            "hosts": {"polytoken": {"capabilities": {"skills": {"status": "verified-active", "evidence": "fixture"}}}}
        }))
        human = self.run_install("--host", "polytoken", "--profile", "standard", "--doctor").stdout
        self.assertIn("skills: static=adapted; activation=unverified", human)
        self.assertNotIn(" — active", human)
        self.assertIn("unvalidated activation labels", human)

    def test_codex_installed_untrusted_admission_is_rendered_with_hooks_remediation(self) -> None:
        activation = self.state / "state/activation-v1.json"
        activation.parent.mkdir(parents=True, exist_ok=True)
        activation.write_text(json.dumps({
            "schema_version": 1,
            "hosts": {"codex": {"capabilities": {"identity_hooks": {
                "status": "installed-untrusted",
                "evidence": "/isolated/evidence/codex-evidence-v1.json",
                "check": "codex-admission-v1",
                "remediation": "open /hooks in interactive Codex and rerun",
            }}}},
        }))
        report = json.loads(self.run_install("--host", "codex", "--profile", "standard", "--doctor", "--json").stdout)
        hook = report["hosts"]["codex"]["capabilities"]["identity_hooks"]["activation"]
        self.assertEqual(hook["status"], "installed-untrusted")
        self.assertIn("/hooks", hook["remediation"])

    def test_doctor_explains_omissions(self) -> None:
        result = self.run_install("--host", "codex", "--profile", "core", "--doctor", "--json")
        omitted = {item["skill"] for item in json.loads(result.stdout)["hosts"]["codex"]["omissions"]}
        self.assertIn("angel", omitted)
        self.assertIn("retro", omitted)
        self.assertNotIn("code", omitted)


if __name__ == "__main__":
    unittest.main()
