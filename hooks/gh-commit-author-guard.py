#!/usr/bin/env python3
"""PreToolUse hook for Bash. Commit-author guard for the multi-account GitHub
setup on this box.

Catches `git commit` in a repo whose `claude.identity` tag points to a real
identity but whose effective git user.name/user.email don't match the identity
map. A mismatch means the commit would be authored under the wrong name —
exactly the leak this system exists to prevent (a pseudonymous repo recording
the real wallet name in commit metadata, or vice versa).

Scope is deliberately minimal — the push hook (gh-identity-guard.py) is the
real backstop, so this hook only blocks when there is a positive mismatch:
  - tagged to a real identity (not local-only / not retired / present in map)
  - AND user.name OR user.email differs from the map values
Untagged repos -> allow (blocking all commits in untagged repos is too noisy;
the push hook will catch the untagged repo before anything leaves the box).
`git commit --dry-run` -> allow (no commit object is written).

Borrows the same expand_tokens + pipeline segmentation as the gmail hook and
gh-identity-guard.py so `bash -c 'git commit ...'` and `git -C <dir> commit`
are seen. Verbs match at command-word position only — never as a substring
inside a commit message.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys

# Shared token-parsing primitives — see gh-identity-guard.py's import note and
# _gh_identity_common's docstring. Single home so a fix can't rot in one copy.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _gh_identity_common import (  # noqa: E402
    GIT_BARE_GLOBAL_FLAGS,
    GIT_DIR_OPTS,
    GIT_VALUE_GLOBAL_FLAGS,
    _base,
    expand_tokens,
    is_assignment as _is_assignment,
    segment,
)

MAP_PATH = os.path.expanduser(
    os.environ.get("CLAUDE_GH_IDENTITY_MAP", "~/.claude/github-identity-map.json")
)  # env override lets the test suite (and adopters) point at a fixture map


def _strip_prefix(seg: list) -> list:
    out = list(seg)
    while out and out[0] == "(":
        out = out[1:]
    if out and out[0].startswith("(") and out[0] != "(":
        out[0] = out[0].lstrip("(")
    while out and _is_assignment(out[0]):
        out = out[1:]
    # Strip `env [-i|-u NAME] [VAR=val...]` wrappers so `env git commit` is
    # still seen as a commit. Lenient posture (this hook allows on doubt —
    # the push hook is the backstop): an unrecognized env option just stops
    # the strip, leaving prog=env -> not-a-commit -> allow.
    while out and _base(out[0]) == "env":
        out = out[1:]
        while out:
            tok = out[0]
            if _is_assignment(tok):
                out = out[1:]
                continue
            if tok in ("-i", "--ignore-environment"):
                out = out[1:]
                continue
            if tok in ("-u", "--unset") and len(out) >= 2:
                out = out[2:]
                continue
            break
    return out


def _accumulate_dir(dir_value: str | None, opt: str, val: str) -> str:
    """git's real -C/--git-dir combination semantics (a 2026-07 review): last
    --git-dir wins; -C is cumulative, so with absolute paths the last -C wins.
    The old code kept only the first -C, so `git -C good -C bad commit`
    validated `good`'s author config while git wrote the commit in `bad`."""
    if opt == "--git-dir":
        return val
    if dir_value is None or os.path.isabs(val):
        return val
    return os.path.normpath(os.path.join(dir_value, val))


def _strip_git_dir_opts(args: list) -> tuple:
    """Strip leading git global opts before the verb. Returns
    (remaining_args, dir_value, configs) — configs are `-c key=val` strings
    (previously `-c` blocked verb detection entirely, so
    `git -c user.email=x commit` was invisible to this guard).

    Value-taking globals (`--namespace foo`, etc.) are stripped WITH their
    value: without this, `git --namespace foo commit` let `foo` displace the
    `commit` verb, so the segment read as not-a-commit and a wrong-author
    commit slipped through (a 2026-07 review, fail-OPEN).
    """
    out = list(args)
    dir_value = None
    configs = []
    while out:
        tok = out[0]
        if tok in GIT_DIR_OPTS:
            if len(out) < 2:
                return out, dir_value, configs  # dangling; verb-detection fails -> allow
            val = out[1]
            if tok in ("-C", "--git-dir"):
                dir_value = _accumulate_dir(dir_value, tok, val)
            out = out[2:]
            continue
        if tok in ("-c", "--config-env"):
            if len(out) < 2:
                return out, dir_value, configs
            configs.append(out[1])
            out = out[2:]
            continue
        if tok in GIT_VALUE_GLOBAL_FLAGS:
            if len(out) < 2:
                return out, dir_value, configs
            out = out[2:]
            continue
        matched = False
        for opt in GIT_DIR_OPTS:
            if tok.startswith(opt + "="):
                val = tok.split("=", 1)[1]
                if opt in ("-C", "--git-dir"):
                    dir_value = _accumulate_dir(dir_value, opt, val)
                out = out[1:]
                matched = True
                break
        if matched:
            continue
        # Known bare global flags and `--x=y` globals consume only themselves.
        # An unknown bare `--flag` might take the next token as its value; this
        # hook leans ALLOW on doubt (push hook is the backstop), so keep the
        # lax strip-one — but the enumerated value-takers above cover the flags
        # that actually displace the verb.
        if tok.startswith("--"):
            out = out[1:]
            continue
        break
    return out, dir_value, configs


def _parse_author_opt(rest: list) -> str | None:
    """Value of `--author=<x>` / `--author <x>` on a commit, else None."""
    for i, tok in enumerate(rest):
        if tok.startswith("--author="):
            return tok.split("=", 1)[1]
        if tok == "--author" and i + 1 < len(rest):
            return rest[i + 1]
    return None


def find_commits(segments: list) -> list:
    """Return descriptors for EVERY real `git commit` segment (not just the
    first — `git commit -m x && git commit --author='Evil <e@x>' -m y` must
    check both; a 2026-07 review). `git commit --dry-run` writes no object,
    so it is skipped.

    Descriptor: dir (-C value or None), configs (`-c` key=val strings),
    author (--author value or None).
    """
    found = []
    for seg in segments:
        cmd = _strip_prefix(seg)
        if not cmd:
            continue
        if _base(cmd[0]) != "git":
            continue
        args, dir_value, configs = _strip_git_dir_opts(cmd[1:])
        if not args or args[0] != "commit":
            continue
        rest = args[1:]
        if "--dry-run" in rest:
            continue  # no commit object written
        found.append({
            "dir": dir_value,
            "configs": configs,
            "author": _parse_author_opt(rest),
        })
    return found


def _git(args: list) -> tuple:
    try:
        proc = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return proc.returncode, proc.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return 1, ""


def deny(reason: str) -> int:
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    json.dump(out, sys.stdout)
    return 0


def evaluate(command: str, cwd: str) -> int:
    try:
        tokens = shlex.split(command, comments=False, posix=True)
        # expand_tokens re-raises on an unparseable nested `bash -c` string;
        # same allow-on-parse-failure posture applies (the sibling guard is
        # the backstop and fails closed on mutation shapes).
        tokens = expand_tokens(tokens)
    except ValueError:
        return 0  # push hook is the backstop; don't block on parse failure here

    segments = segment(tokens)
    commits = find_commits(segments)
    if not commits:
        return 0  # allow — no commit-class command

    try:
        with open(MAP_PATH, "r", encoding="utf-8") as f:
            idmap = json.load(f)
    except (OSError, json.JSONDecodeError):
        return 0  # can't validate -> allow; push hook backstops
    identities = idmap.get("identities", {})

    for commit in commits:
        reason = _check_commit(commit, cwd, identities)
        if reason is not None:
            return deny(reason)
    return 0


def _check_commit(commit: dict, cwd: str, identities: dict) -> str | None:
    """Validate one `git commit` descriptor's author against its repo tag.
    Returns a deny reason, or None to allow. Leans ALLOW on any ambiguity
    (untagged repo, unknown tag, missing map values) — the push hook is the
    real backstop for anything that leaves the box."""
    base = commit["dir"] if commit["dir"] else cwd
    rc, top = _git(["-C", base, "rev-parse", "--show-toplevel"])
    if rc != 0 or not top:
        return None  # not a repo (or unreadable) -> allow; push hook backstops

    rc, tag = _git(["-C", top, "config", "--local", "--get", "claude.identity"])
    if rc != 0 or not tag:
        return None  # untagged -> allow (too noisy to block)

    entry = identities.get(tag)
    if entry is None:
        return None  # unknown tag -> allow here; push hook will deny
    if entry.get("retired") is True or entry.get("push") is False:
        # Not a "real identity"; commit author isn't the leak vector here, and
        # the push hook blocks any push. Allow the local commit.
        return None

    want_name = entry.get("user_name")
    want_email = entry.get("user_email")
    if not want_name or not want_email:
        return None  # map has no author values for this identity -> nothing to check

    _, have_name = _git(["-C", top, "config", "--get", "user.name"])
    _, have_email = _git(["-C", top, "config", "--get", "user.email"])

    # Per-invocation overrides beat repo config: `git -c user.name=X commit`
    # and `git commit --author="Name <email>"` author the commit with the
    # override value, so compare against THAT when present.
    for cfg in commit.get("configs", []):
        if "=" not in cfg:
            continue
        k, v = cfg.split("=", 1)
        k = k.strip().lower()
        if k == "user.name":
            have_name = v
        elif k == "user.email":
            have_email = v
    author = commit.get("author")
    if author:
        if "<" in author and author.rstrip().endswith(">"):
            a_name, a_email = author.split("<", 1)
            have_name = a_name.strip()
            have_email = a_email.rstrip().rstrip(">").strip()
        elif author.strip() == want_name:
            # git-commit(1) pattern form (bare, no "Name <email>"): git searches
            # history and copies that author. When the pattern equals this
            # identity's own name, it resolves to the expected identity — allow.
            return None
        else:
            # Pattern form that isn't obviously this identity: git resolves it
            # from commit history at commit time, so the resulting author can't
            # be verified statically. Not "unparseable" — it's a documented git
            # feature we decline to guess at.
            return (
                f"`git commit --author={author!r}` uses git's pattern form "
                '(no "Name <email>"), which resolves the author from commit '
                f"history at commit time — this hook can't statically verify "
                f'the result in a repo tagged {tag!r}. Use the explicit '
                f'"Name <email>" form (e.g. --author="{want_name} '
                f'<{want_email}>") or drop the flag.'
            )

    if have_name == want_name and have_email == want_email:
        return None  # match -> allow

    return (
        f"Commit author mismatch. Repo tagged {tag!r} expects "
        f"user.name={want_name!r} / user.email={want_email!r}, but this "
        f"commit would use user.name={have_name or '(unset)'!r} / "
        f"user.email={have_email or '(unset)'!r}. Fix before committing:\n"
        f'  git -C {top} config user.name "{want_name}" && '
        f'git -C {top} config user.email "{want_email}"'
    )


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    tool_input = data.get("tool_input", {}) or {}
    cmd = tool_input.get("command", "")
    if not cmd:
        return 0

    cwd = tool_input.get("cwd") or data.get("cwd") or os.getcwd()

    try:
        return evaluate(cmd, cwd)
    except Exception:  # noqa: BLE001 — never break an unrelated Bash command.
        return 0


if __name__ == "__main__":
    sys.exit(main())
