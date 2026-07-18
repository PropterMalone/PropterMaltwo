"""Shared shell-token parsing primitives for the gh-identity guard hooks.

gh-identity-guard.py (push/identity) and gh-commit-author-guard.py (commit
author) both tokenize a Bash command, expand `bash -c '<shell>'` wrappers, and
split on pipeline delimiters. That core was duplicated VERBATIM across the two
files — and a 2026-07 /angel review found the cost: a correctness fix landed
in one copy and not the other (the expand_tokens ordering bug below, and the
`-C` last-wins bug). This module is the single home for the identical
primitives so a fix can't rot in one copy.

What stays per-hook (intentional divergence, documented in each): the push hook
strips `env`/global-opt prefixes strictly and fails CLOSED on ambiguity; the
commit hook leans ALLOW on ambiguity because the push hook is its backstop.
Only the format-invariant token machinery lives here.

Hooks import this as a sibling module via a sys.path insert of their own dir.
"""

from __future__ import annotations

import shlex

PIPELINE_DELIMS = {"|", "||", "&&", ";", "&"}
SHELL_RUNNERS = {"bash", "sh", "zsh", "dash"}  # tokens that take -c '<shell>'

# Options that take a directory/path value and may precede the subcommand verb.
# Stripped (with their value) before reading the verb so `git -C dir push` and
# `git --git-dir x --work-tree y push` parse correctly.
GIT_DIR_OPTS = {"-C", "--git-dir", "--work-tree"}

# git global options that consume the NEXT token as a value (space form) and may
# sit before the subcommand verb. Stripped WITH their value so the flag's value
# is never mistaken for the verb (e.g. `git --namespace foo commit` — without
# this, `foo` displaces `commit` and the command reads as not-a-commit, a
# fail-OPEN the 2026-07 review caught). `-c`/`--config-env` are handled
# separately (their value is surfaced for the dangerous-config check).
GIT_VALUE_GLOBAL_FLAGS = {"--namespace", "--super-prefix", "--attr-source"}

# git global flags that never take a separate-token value.
GIT_BARE_GLOBAL_FLAGS = {
    "--no-pager", "--paginate", "-p", "-P", "--bare", "--no-replace-objects",
    "--literal-pathspecs", "--glob-pathspecs", "--noglob-pathspecs",
    "--icase-pathspecs", "--no-optional-locks", "--no-lazy-fetch",
    "--no-advice", "--version", "--help",
}


def _base(token: str) -> str:
    return token.split("/")[-1]


def expand_tokens(tokens: list, _depth: int = 0) -> list:
    """Expand string-as-command arguments IN PLACE, preserving execution order.

    `bash -c '<shell>'` (and sh/zsh/dash) and `env -S '<shell>'` evaluate the
    quoted string as shell. shlex.split keeps that string as one token, hiding
    any push/commit invocation inside it — so tokenize the inner string and
    splice it back AT THE WRAPPER'S POSITION, fenced by ";" delimiters so
    segment() breaks it into its own command segment.

    Splicing in place (not appending to the end) is load-bearing: callers that
    track sequential state across segments — the push hook's cd-taint and
    remote-mutation walk — depend on segment order matching real left-to-right
    execution order. The previous append-to-end approach put an expanded
    `git remote set-url ...` AFTER a plain `git push` that textually preceded
    it, so the walk saw the push before the mutation that should have tainted
    it and allowed a wrong-remote push (2026-07 review, Critical). git runs
    them left-to-right; so must we.

    Bounded recursion (depth 3) to prevent pathological nesting.
    """
    if _depth >= 3:
        return list(tokens)
    out = []
    i = 0
    n = len(tokens)
    while i < n:
        t = tokens[i]
        base = _base(t)
        inner_str = None
        # bash/sh/zsh/dash -c '<shell>'
        if base in SHELL_RUNNERS and i + 2 < n and tokens[i + 1] == "-c":
            inner_str = tokens[i + 2]
        # env -S '<shell>'
        elif base == "env" and i + 2 < n and tokens[i + 1] == "-S":
            inner_str = tokens[i + 2]
        if inner_str is not None:
            try:
                inner = shlex.split(inner_str, posix=True)
                inner = expand_tokens(inner, _depth + 1)
                out.append(";")
                out.extend(inner)
                out.append(";")
            except ValueError:
                # An unparseable inner shell string must NOT be silently
                # dropped: a mutation verb inside `bash -c` with an unclosed
                # quote would otherwise vanish from the token stream and both
                # guards would ALLOW (fail-open; cross-model review catch,
                # 2026-07). Re-raise so callers treat it exactly like a
                # top-level parse failure.
                raise
            i += 3
            continue
        out.append(t)
        i += 1
    return out


def segment(tokens: list) -> list:
    """Split a flat token stream into command segments on pipeline delimiters.

    Each segment is the argv of one simple command (verb + args). Empty
    segments (consecutive delimiters) are dropped.
    """
    segs = []
    cur = []
    for t in tokens:
        if t in PIPELINE_DELIMS:
            if cur:
                segs.append(cur)
                cur = []
        else:
            cur.append(t)
    if cur:
        segs.append(cur)
    return segs


def is_assignment(token: str) -> bool:
    if "=" not in token:
        return False
    name = token.split("=", 1)[0]
    return bool(name) and (name[0].isalpha() or name[0] == "_") and all(
        c.isalnum() or c == "_" for c in name
    )
