#!/usr/bin/env python3
"""Sanitize over-escaped Bash() entries in the permission allowlist.

Claude Code's "always allow" persistence path over-escapes shell-special
characters (parens, quotes, dollars) when storing Bash command patterns. The
resulting strings can't match anything in production AND trip the matcher's
AST parser with `unhandled node type: string` errors that block long-running
sessions with permission prompts.

This hook runs on Stop (end of every Claude turn) and removes broken entries
from `~/.claude/settings.local.json` and the active project's
`.claude/settings.local.json` (if present). Idempotent: clean files are no-ops.

A backup is written to `<file>.bak.<timestamp>` ONLY when entries are removed,
so this hook doesn't generate backup-file-pollution on every run.

Telemetry: writes a line to `~/.claude/state/sanitize-allowlist.log` per run
with counts. Lets us spot whether the upstream binary is still producing bad
entries (i.e., is the bug fixed yet) without manual re-investigation.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# Over-escape signatures: Claude Code's auto-permission-add path produces these
# two-char sequences inside Bash() strings. None are legitimate shell syntax in
# this context — `\(` / `\)` / `\$` / `\.` aren't quote-escape constructs, and
# `\n` would only appear in a Bash() pattern if someone literally typed a
# backslash-n (vanishingly rare). NOT included: `\'` and `\"`, which CAN be
# legitimate (shell quote-escape idioms like `echo 'it'\''s ok'`).
OVER_ESCAPE_PATTERNS = (r"\(", r"\)", r"\$", r"\.", r"\n")

# Truncation suffixes seen on broken auto-add entries. The auto-add path
# truncates inside a quoted argument and appends `*` or `*)`, producing
# specs the matcher's AST parser rejects (`unhandled node type: string`).
TRUNCATION_SUFFIXES = (" *", "' *", '" *')


def is_broken_bash_entry(s: str) -> bool:
    """True iff this allow entry looks over-escaped beyond what the matcher can parse.

    Two failure modes seen in practice, both produced by Claude Code's
    auto-permission-add path:

    1. Over-escape of shell-specials (`\\(`, `\\)`, `\\$`, `\\.`, `\\n`).
       Real bash command specs don't contain these as literal two-char sequences.
       Note: `\\'` and `\\"` are NOT in this set — they're legitimate quote-escape
       idioms (e.g., `Bash(echo 'it'\\''s ok' *)`) and must not be flagged.

    2. Truncation: a quoted argument cut mid-string with `*` appended — e.g.
       `Bash(python3 -c ' *)`. The matcher's AST parser then errors out with
       `unhandled node type: string`, falling back to prompting EVEN FOR
       UNRELATED TOOL CALLS (matcher iterates all entries).

    Either condition means the entry can never match its intended command
    and actively breaks the matcher for other entries — safe to remove.
    """
    if not isinstance(s, str):
        return False
    if not s.startswith("Bash("):
        return False
    inner = s[len("Bash("):]
    if inner.endswith(")"):
        inner = inner[:-1]
    if any(pat in inner for pat in OVER_ESCAPE_PATTERNS):
        return True
    # Truncation signal: ends with one of the broken-suffix patterns AND has
    # an unmatched quote (single OR double). Both signals together avoid the
    # false-positive on legitimate "ends with ` *`" globs.
    if any(inner.endswith(suf) for suf in TRUNCATION_SUFFIXES):
        sq = len(re.findall(r"(?<!\\)'", inner))
        dq = len(re.findall(r'(?<!\\)"', inner))
        if (sq % 2 != 0) or (dq % 2 != 0):
            return True
    return False


def sanitize_file(path: Path) -> tuple[int, int]:
    """Return (kept, removed). 0/0 if file missing or has no permissions block."""
    if not path.exists():
        return (0, 0)
    try:
        d = json.load(path.open())
    except (json.JSONDecodeError, OSError):
        return (0, 0)
    perms = d.get("permissions")
    if not isinstance(perms, dict):
        return (0, 0)
    allow = perms.get("allow")
    if not isinstance(allow, list):
        return (0, 0)

    bad = [a for a in allow if is_broken_bash_entry(a)]
    if not bad:
        return (len(allow), 0)

    backup = path.with_suffix(
        path.suffix + f".bak.{datetime.now().strftime('%Y%m%dT%H%M%S')}"
    )
    backup.write_text(path.read_text())

    perms["allow"] = [a for a in allow if not is_broken_bash_entry(a)]
    path.write_text(json.dumps(d, indent=2))
    return (len(perms["allow"]), len(bad))


def telemetry(msg: str) -> None:
    state = Path.home() / ".claude" / "state"
    state.mkdir(parents=True, exist_ok=True)
    log = state / "sanitize-allowlist.log"
    with log.open("a") as f:
        f.write(f"{datetime.now().isoformat()} {msg}\n")


def main() -> int:
    targets = [Path.home() / ".claude" / "settings.local.json"]
    cwd = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    proj_settings = cwd / ".claude" / "settings.local.json"
    if proj_settings.exists() and proj_settings.resolve() != targets[0].resolve():
        # Path-traversal guard: CLAUDE_PROJECT_DIR is read from env and can be
        # attacker-controlled (transcript injection, malicious cwd). Only
        # process settings.local.json files under the user's home dir — the
        # hook MUTATES these files, so unbounded paths are a real risk.
        try:
            resolved = proj_settings.resolve()
            if resolved.is_relative_to(Path.home()):
                targets.append(proj_settings)
            else:
                telemetry(f"REJECTED out-of-home proj_settings: {resolved}")
        except (OSError, ValueError):
            # symlink resolution failure / weird path — skip silently
            pass

    total_removed = 0
    parts = []
    for t in targets:
        kept, removed = sanitize_file(t)
        total_removed += removed
        if removed:
            parts.append(f"{t}: kept={kept} removed={removed}")
    if total_removed:
        telemetry(" | ".join(parts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
