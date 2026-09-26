from __future__ import annotations

import contextlib
import io
from pathlib import Path
import stat
import tempfile
import unittest

from tests import run_quality_gates


class QualityGateRunnerTests(unittest.TestCase):
    def test_run_quality_gates_propagates_each_child_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            commands: list[tuple[str, ...]] = []
            for index in range(len(run_quality_gates.COMMANDS)):
                script = root / f"gate-{index}.sh"
                script.write_text("#!/usr/bin/env bash\nprintf 'gate-%s-ran\\n' " + str(index) + "\nexit \"${FAIL_GATE_" + str(index) + ":-0}\"\n")
                script.chmod(script.stat().st_mode | stat.S_IXUSR)
                commands.append((str(script),))

            for failed_index in range(len(commands)):
                with self.subTest(failed_index=failed_index):
                    env = {f"FAIL_GATE_{failed_index}": "9"}
                    results = run_quality_gates.run_all(commands, env=env)
                    self.assertEqual(len(results), len(commands))
                    self.assertEqual([result.returncode for result in results].count(9), 1)
                    self.assertEqual(results[failed_index].returncode, 9)
                    self.assertTrue(all(f"gate-{index}-ran" in result.stdout for index, result in enumerate(results)))

    def test_deterministic_gate_covers_every_test_module_except_itself(self) -> None:
        command = run_quality_gates.COMMANDS[-2]
        self.assertEqual(command, ("python3", "tests/run_deterministic_suite.py"))
        from tests import run_deterministic_suite
        modules = set(run_deterministic_suite.module_names())
        discovered = {path.stem for path in Path(__file__).resolve().parent.glob("test_*.py")}
        self.assertEqual(modules, discovered - {"test_run_quality_gates"})
        self.assertIn("test_installer", modules)
        self.assertIn("test_codex_admission", modules)
        self.assertIn("test_polytoken_release_gate", modules)

    def test_main_never_prints_success_when_any_child_fails(self) -> None:
        fake = [
            __import__("subprocess").CompletedProcess(["gate"], 0, "ok\n", ""),
            __import__("subprocess").CompletedProcess(["gate"], 3, "", "bad\n"),
        ]
        original_commands = run_quality_gates.COMMANDS
        original_run_all = run_quality_gates.run_all
        run_quality_gates.COMMANDS = (("gate-a",), ("gate-b",))
        run_quality_gates.run_all = lambda: fake
        try:
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = run_quality_gates.main()
        finally:
            run_quality_gates.COMMANDS = original_commands
            run_quality_gates.run_all = original_run_all
        self.assertEqual(code, 1)
        self.assertIn("gate-b", stdout.getvalue())
        self.assertIn("QUALITY GATES FAILED", stdout.getvalue())
        self.assertNotIn("QUALITY GATES PASSED", stdout.getvalue())
        self.assertIn("bad", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
