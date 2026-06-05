#!/usr/bin/env python3
# pattern: imperative shell (spawns the hook as a subprocess, writes/reads temp files).
"""Standalone test for sanitize-permission-allowlist.py.

Run directly (`python3 hooks/test_sanitize_allowlist.py`) or via test-hooks.sh.
No pytest dependency — plain asserts, exit 0 on pass / 1 on fail.

Isolation: the hook reads/writes `~/.claude/settings.local.json` and writes
telemetry to `~/.claude/state/`. We point $HOME at a throwaway tempdir for the
subprocess so the real ~/.claude is never touched. `Path.home()` (and thus the
hook's home-dir path-traversal guard) resolves against the overridden $HOME, so
a project settings file placed inside that temp home also passes the guard.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "sanitize-permission-allowlist.py"

# Mix of entries the hook must distinguish:
#   BROKEN (must be removed):
#     - over-escaped paren     Bash(echo \(foo\))
#     - over-escaped dollar    Bash(echo \$HOME)
#     - over-escaped dot       Bash(grep foo\.bar *)
#     - truncated single-quote Bash(python3 -c ' *)
#   CLEAN (must be kept):
#     - plain command          Bash(ls -la)
#     - glob suffix, balanced  Bash(npm run *)
#     - legit quote-escape     Bash(echo 'it'\''s ok' *)   [\' is NOT an over-escape signal]
#     - non-Bash entry         Read(//**)
BROKEN = [
    r"Bash(echo \(foo\))",
    r"Bash(echo \$HOME)",
    r"Bash(grep foo\.bar *)",
    "Bash(python3 -c ' *)",
]
CLEAN = [
    "Bash(ls -la)",
    "Bash(npm run *)",
    r"Bash(echo 'it'\''s ok' *)",
    "Read(//**)",
]


def run_hook(home: Path) -> None:
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin"}
    # CLAUDE_PROJECT_DIR unset → hook falls back to cwd; we set it to home so the
    # project-settings branch is exercised against an in-home (allowed) path.
    env["CLAUDE_PROJECT_DIR"] = str(home)
    subprocess.run(
        [sys.executable, str(HOOK)],
        env=env,
        check=True,
        capture_output=True,
        timeout=30,
    )


def main() -> int:
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="sanitize-test-") as td:
        home = Path(td)
        settings = home / ".claude" / "settings.local.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(
            json.dumps({"permissions": {"allow": BROKEN + CLEAN}}, indent=2)
        )

        run_hook(home)

        after = json.loads(settings.read_text())
        kept = after["permissions"]["allow"]

        # Every clean entry must survive (regression guard against over-deletion).
        for c in CLEAN:
            if c not in kept:
                failures.append(f"clean entry wrongly removed: {c!r}")
        # Every broken entry must be gone.
        for b in BROKEN:
            if b in kept:
                failures.append(f"broken entry NOT removed: {b!r}")
        # Exact-set check: kept == CLEAN, order-independent.
        if set(kept) != set(CLEAN):
            extra = set(kept) - set(CLEAN)
            missing = set(CLEAN) - set(kept)
            failures.append(f"kept set mismatch extra={extra} missing={missing}")
        # A backup must exist (hook backs up only when it removes something).
        backups = list(settings.parent.glob("settings.local.json.bak.*"))
        if not backups:
            failures.append("no backup written despite removals")

    # Idempotency / regression: an all-clean file must be left untouched (no backup).
    with tempfile.TemporaryDirectory(prefix="sanitize-clean-") as td:
        home = Path(td)
        settings = home / ".claude" / "settings.local.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        original = json.dumps({"permissions": {"allow": CLEAN}}, indent=2)
        settings.write_text(original)

        run_hook(home)

        if json.loads(settings.read_text())["permissions"]["allow"] != CLEAN:
            failures.append("clean-only file was modified (over-deletion)")
        if list(settings.parent.glob("settings.local.json.bak.*")):
            failures.append("backup written for a clean-only file (no-op expected)")

    if failures:
        for f in failures:
            print(f"  FAIL sanitize-permission-allowlist.py: {f}")
        return 1
    print("  PASS sanitize-permission-allowlist.py / broken removed, clean kept")
    print("  PASS sanitize-permission-allowlist.py / clean-only file untouched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
