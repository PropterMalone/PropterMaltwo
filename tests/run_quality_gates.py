#!/usr/bin/env python3
"""Run the seven AC.10 commands plus the complete non-recursive deterministic suite."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
COMMANDS: tuple[tuple[str, ...], ...] = (
    ("bash", "hooks/test-hooks.sh"),
    ("python3", "hooks/test-gh-identity-hooks.py"),
    ("python3", "scripts/validate-personas.py"),
    ("bash", "scripts/test_scripts.sh"),
    ("python3", "-m", "pytest", "scripts/test_adr_sweep.py", "-q"),
    ("bash", "scripts/adr-falsifier-sweep.sh", "--dry-run", "--no-tasks", "--no-notify", "--only", "PropterMaltwo"),
    ("python3", "tests/run_deterministic_suite.py"),
    ("python3", "-m", "unittest", "tests.test_portability_adr_admission_consistency"),
)
CWD_OVERRIDES = {
    2: ROOT / "skills/angel",
    3: ROOT / "skills/angel",
}


def run_all(
    commands: Sequence[Sequence[str]] = COMMANDS,
    *,
    env: Mapping[str, str] | None = None,
) -> list[subprocess.CompletedProcess[str]]:
    results: list[subprocess.CompletedProcess[str]] = []
    for index, command in enumerate(commands):
        cwd = CWD_OVERRIDES.get(index, ROOT)
        results.append(
            subprocess.run(
                list(command),
                cwd=cwd,
                env=dict(env) if env is not None else os.environ.copy(),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        )
    return results


def main() -> int:
    results = run_all()
    failures = 0
    for index, (command, result) in enumerate(zip(COMMANDS, results, strict=True), start=1):
        rendered = " ".join(command)
        status = "PASS" if result.returncode == 0 else "FAIL"
        print(f"[{index}/{len(COMMANDS)}] {status} ({result.returncode}): {rendered}")
        if result.stdout:
            print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
        if result.stderr:
            print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)
        if result.returncode != 0:
            failures += 1
    if failures:
        print(f"QUALITY GATES FAILED: {failures}/{len(COMMANDS)} command(s) failed.")
        return 1
    print(f"QUALITY GATES PASSED: {len(COMMANDS)}/{len(COMMANDS)} command(s) passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
