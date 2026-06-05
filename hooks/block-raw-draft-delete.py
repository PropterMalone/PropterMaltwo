#!/usr/bin/env python3
# OPTIONAL hook: only relevant if you use the gmail/gws integration; harmless to keep otherwise (it only fires on matching tool calls).
"""PreToolUse hook for Bash. Deny raw `gws ... drafts delete` invocations.

Rationale: Gmail drafts.delete is PERMANENT (no Trash) and bypasses the
clobber-guard built into the `gmail` CLI wrapper. A user who edits drafts in
Gmail in place can have a "superseded" draft (created by a prior turn) that
holds hand edits. Deleting it raw clobbers those edits irreversibly. Use
`gmail delete --draft-id <id>` instead: it re-reads the live draft and refuses
if it was edited since the tool wrote it.

Tokenization mirrors block-gmail-ack-warnings.py so quoted strings, pipelines,
and `bash -c '<shell>'` wrappers can't smuggle the call past the matcher.
"""

from __future__ import annotations

import json
import shlex
import sys

PIPELINE_DELIMS = {"|", "||", "&&", ";", "&"}
SHELL_RUNNERS = {"bash", "sh", "zsh", "dash"}


def is_gws(token: str) -> bool:
    s = token.lstrip("(")
    return s == "gws" or s.endswith("/gws")


def expand_tokens(tokens: list) -> list:
    """Recursively expand `bash -c '<shell>'` / `env -S '<shell>'` string args."""
    expanded = list(tokens)
    for _depth in range(3):
        next_extra = []
        i, n = 0, len(expanded)
        while i < n:
            t = expanded[i]
            base = t.split("/")[-1]
            if base in SHELL_RUNNERS and i + 2 < n and expanded[i + 1] == "-c":
                try:
                    next_extra.extend(shlex.split(expanded[i + 2], posix=True))
                except ValueError:
                    pass
                i += 3
                continue
            if base == "env" and i + 2 < n and expanded[i + 1] == "-S":
                try:
                    next_extra.extend(shlex.split(expanded[i + 2], posix=True))
                except ValueError:
                    pass
                i += 3
                continue
            i += 1
        if not next_extra:
            break
        expanded.extend(next_extra)
    return expanded


def find_violation(tokens: list) -> bool:
    """True if any gws command segment contains the consecutive tokens
    `drafts delete` (i.e. `gws gmail users drafts delete ...`)."""
    tokens = expand_tokens(tokens)
    i, n = 0, len(tokens)
    while i < n:
        if is_gws(tokens[i]):
            seg = []
            j = i + 1
            while j < n and tokens[j] not in PIPELINE_DELIMS:
                seg.append(tokens[j].rstrip(")"))
                j += 1
            for k in range(len(seg) - 1):
                if seg[k] == "drafts" and seg[k + 1] == "delete":
                    return True
            i = j
        else:
            i += 1
    return False


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    cmd = data.get("tool_input", {}).get("command", "")
    if not cmd:
        return 0
    try:
        tokens = shlex.split(cmd, comments=False, posix=True)
    except ValueError:
        return 0
    if not find_violation(tokens):
        return 0

    reason = (
        "Blocked: raw `gws ... drafts delete` is not allowed. Gmail drafts.delete "
        "is PERMANENT (no Trash) and bypasses the clobber-guard. If you edit drafts "
        "in place, deleting one raw can irreversibly clobber your edits. Use "
        "`gmail delete --draft-id <id>` instead -- it re-reads the live draft and "
        "refuses (unless --force) if it was edited in Gmail since the tool wrote it."
    )
    deny = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    json.dump(deny, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
