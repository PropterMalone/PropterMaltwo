#!/usr/bin/env python3
"""Fingerprint the exact trusted reducer surface admitted by the live probe."""
from __future__ import annotations

import hashlib
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
FILES = (
    SCRIPT_DIR / "runner-fingerprint.py",
    SCRIPT_DIR / "dispatch-integration.sh",
    SCRIPT_DIR / "shard-integration.py",
    SCRIPT_DIR / "run-reducer-sandbox.py",
    SCRIPT_DIR / "integration_common.py",
    SCRIPT_DIR / "probe-integration-runner.sh",
    SKILL_DIR / "reducer.md",
    SKILL_DIR / "schemas/integration-decisions-v1.json",
)


def fingerprint():
    digest = hashlib.sha256()
    for path in FILES:
        relative = path.relative_to(SKILL_DIR).as_posix().encode()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        content = path.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


if __name__ == "__main__":
    print(fingerprint())
