#!/usr/bin/env python3
# OPTIONAL hook: only relevant if you use the gmail/gws integration; harmless to keep otherwise (it only fires on matching tool calls).
"""PreToolUse hook for Bash. Deny when the command invokes a `gmail` CLI
wrapper with the warning-acknowledgement flag.

Rationale: the gmail sanitizer's warnings are tuned to be tight (false
positives on bullets, indented code, and signature blocks are filtered out).
A warning that fires now is real — address it directly (restructure body,
use --unwrap, or fix the specific issue) rather than bypassing with the
acknowledgement flag.

Implementation note: an earlier shell version fired on any substring match.
That blocked its own introduction commit because the flag name appeared as
literal text in the commit-message HEREDOC. This version shell-tokenizes the
command and only fires when the flag is a real argv token of a real `gmail`
invocation (i.e. not inside a quoted string).
"""

from __future__ import annotations

import json
import shlex
import sys

PIPELINE_DELIMS = {"|", "||", "&&", ";", "&"}
FLAG_NAMES = {"--ack-warnings"}
SHELL_RUNNERS = {"bash", "sh", "zsh", "dash"}  # tokens that take -c '<shell>'


def is_gmail_command(token: str) -> bool:
    # Strip any leading subshell parens (`(gmail` from `(gmail --flag)`).
    stripped = token.lstrip("(")
    return stripped == "gmail" or stripped.endswith("/gmail")


def expand_tokens(tokens: list) -> list:
    """Recursively expand string-as-command arguments.

    `bash -c '<shell>'`, `sh -c '<shell>'`, `zsh -c '<shell>'`, `dash -c '<shell>'`,
    and `env -S '<shell>'` all evaluate the quoted string as shell. shlex.split
    on the outer command keeps the inner string as a single token, which would
    hide a `gmail --ack-warnings` invocation inside it. Tokenize the inner
    string and add it to the search space.

    Bounded recursion (depth 3) to prevent pathological nesting.
    """
    expanded = list(tokens)
    for _depth in range(3):
        next_extra = []
        i = 0
        n = len(expanded)
        while i < n:
            t = expanded[i]
            # bash/sh/zsh/dash -c '<shell>'
            base = t.split("/")[-1]
            if base in SHELL_RUNNERS and i + 2 < n and expanded[i + 1] == "-c":
                try:
                    next_extra.extend(shlex.split(expanded[i + 2], posix=True))
                except ValueError:
                    pass
                i += 3
                continue
            # env -S '<shell>'
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
    tokens = expand_tokens(tokens)
    i = 0
    n = len(tokens)
    while i < n:
        if is_gmail_command(tokens[i]):
            j = i + 1
            while j < n and tokens[j] not in PIPELINE_DELIMS:
                if tokens[j].rstrip(")") in FLAG_NAMES:
                    return True
                j += 1
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
        "Blocked: gmail commands must not use the warning-acknowledgement flag. "
        "The sanitizer warnings are tuned tight (false positives on bullets/indented "
        "code/signatures are filtered). If a warning fires, address it: "
        "(1) restructure the body to single-line paragraphs, (2) pass --unwrap to "
        "auto-join, or (3) fix the specific issue (URL adjacent to punctuation, "
        "real mojibake, etc.)."
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
