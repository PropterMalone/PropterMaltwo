#!/usr/bin/env python3
"""Run every deterministic test module except the aggregate-runner self-tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

TESTS = Path(__file__).resolve().parent
EXCLUDED = {"test_run_quality_gates.py"}


def module_paths() -> list[Path]:
    return [path for path in sorted(TESTS.glob("test_*.py")) if path.name not in EXCLUDED]


def module_names() -> list[str]:
    return [path.stem for path in module_paths()]


def main() -> int:
    paths = module_paths()
    if not paths:
        print("no deterministic test modules discovered", file=sys.stderr)
        return 2
    suite = unittest.TestSuite()
    for path in paths:
        spec = importlib.util.spec_from_file_location(f"proptermaltwo_tests_{path.stem}", path)
        if spec is None or spec.loader is None:
            print(f"cannot load deterministic test module: {path}", file=sys.stderr)
            return 2
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
