#!/usr/bin/env python3
"""PreToolUse hook for Bash. Push-identity validator for the multi-account
GitHub setup on this box.

Ground truth (verified): on Malone, SSH remote URLs decide push identity, not
`gh auth switch`. ~/.ssh/config maps host aliases to keys:
  github.com            -> PropterMalone key
  github.com-personal  -> your-personal-account key
  github.com-retiredaccount   -> RetiredAccount key (retired)
`gh auth switch` only affects `gh repo create`/`pr create` and HTTPS git auth.

This hook is a PURE VALIDATOR. It NEVER runs `gh auth switch` or any other
command with global side effects — the allow path has zero side effects beyond
a best-effort audit-log line when an override env var is used. On any decision
it cannot make safely, it DENIES (fail-closed).

Identity is read from `git config --local claude.identity <id>` and validated
against ~/.claude/github-identity-map.json.

It blocks (denies) push-class commands when:
  - the repo is untagged (no claude.identity)            -> tag-and-retry
  - the tag is local-only / retired / push==false        -> blocked by policy
  - the target remote's SSH host != map ssh_host         -> wrong-identity push
  - an HTTPS remote owner != map gh_account              -> wrong-identity push
  - the remote URL is unrecognized                       -> can't verify -> deny
  - gh-state (active gh account) != map gh_account for
    gh-CLI create ops or HTTPS push                       -> switch-and-retry
  - a push-ish segment can't be parsed                    -> tag-and-retry
  - a `cd`/`pushd` earlier in the same command moved to an unresolvable
    directory, or `git remote set-url|add` precedes the push -> deny
  - GIT_SSH*/GIT_CONFIG*/GIT_DIR/GIT_WORK_TREE env assignments, or `git -c`
    config overrides touching remote./url./http./credential./core.sshCommand,
    appear on a push segment                              -> deny

Threat model (decided a 2026-07, option A per identity-hook-angel-findings.md):
ACCIDENT-PREVENTION NET, not adversary-proof. Static parsing cannot defeat a
motivated actor with shell access (documented residual: git aliases, >3-level
bash -c nesting, exotic env routing beyond the prefixes denied above). The goal
is catching realistic wrong-identity accidents.

Every push-class segment in a compound command is validated (not just the
first); segment order is tracked so `cd` and remote-mutation earlier in the
command affect later pushes.

Escape hatches (env vars set ON the command line, e.g. `CLAUDE_IDENTITY_OVERRIDE=x git push`):
  CLAUDE_IDENTITY_OVERRIDE=<id>  bypasses ONLY the untagged-block; the host/gh
                                 checks still run against <id>. Every use is
                                 logged to the hook-errors log.
  CLAUDE_IDENTITY=<id>           supplies the identity for a brand-new untagged
                                 `gh repo create` (which has no repo dir yet).

Implementation borrows expand_tokens + pipeline segmentation VERBATIM in spirit
from block-gmail-ack-warnings.py: it shell-tokenizes, recursively expands
`bash/sh/zsh/dash -c '<shell>'` and `env -S '<shell>'` (depth 3), and matches
verbs only at command-word position — never as substrings inside a quoted
commit message / filename / echo.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys

# Shared token-parsing primitives (expand_tokens, segment, constants) live in a
# sibling module so a fix can't rot in one hook copy — see _gh_identity_common's
# docstring. Import via a sys.path insert of this file's own directory.
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

# When shlex can't parse a command, we can't segment it — so we fall back to a
# substring test to decide whether to fail closed. It MUST be tight: a bare
# "push" matched innocent commands (`echo "how to push"`, `grep pushd`), and
# any command that ALSO failed to shlex-parse (unbalanced quotes in a heredoc,
# etc.) was then denied — a false positive on non-git Bash. Require an actual
# git-push / gh-create shape at a word boundary instead.
_PUSHY_ON_PARSE_FAIL = re.compile(
    r"\bgit\b[^\n|&;]*\b(?:push|send-pack)\b"
    r"|\bgh\b[^\n|&;]*\b(?:repo|pr|release)\b[^\n|&;]*\bcreate\b"
    r"|\bgh\b[^\n|&;]*\bpr\b[^\n|&;]*\bmerge\b"
)


class ParseError(Exception):
    """Raised when a segment looks push-ish but can't be parsed safely."""


def _strip_prefix(seg: list) -> list:
    """Strip a leading `(` subshell paren and env-var ASSIGNMENTS (FOO=bar)
    from the front of a segment. Returns the remaining tokens (the command).

    Note: env-var assignments are returned separately by collect_env_assigns;
    this helper only removes them from the verb-detection stream.
    """
    out = list(seg)
    # Strip leading bare "(" tokens.
    while out and out[0] == "(":
        out = out[1:]
    # A leading token may be "(git" — strip the paren.
    if out and out[0].startswith("(") and out[0] != "(":
        out[0] = out[0].lstrip("(")
    # Strip leading VAR=value assignments.
    while out and _is_assignment(out[0]):
        out = out[1:]
    return out


def _accumulate_dir(dir_value: str | None, opt: str, val: str) -> str:
    """Combine a `-C`/`--git-dir` value into the running repo-dir resolution,
    matching git's real semantics (2026-07 review, Critical):
      --git-dir  → last one wins (points AT the .git dir, not a chdir)
      -C         → CUMULATIVE: a non-absolute subsequent -C is resolved
                   relative to the preceding -C, so with absolute paths the
                   last -C wins. The old code kept only the FIRST -C, so
                   `git -C good -C evil push` validated `good` and let the
                   push run from `evil`.
    """
    if opt == "--git-dir":
        return val
    if dir_value is None or os.path.isabs(val):
        return val
    return os.path.normpath(os.path.join(dir_value, val))


def collect_env_assigns(seg: list) -> dict:
    """Collect leading VAR=value assignments from a segment (after stripping a
    leading paren). These are how escape-hatch env vars arrive on a command.
    """
    env = {}
    out = list(seg)
    while out and out[0] == "(":
        out = out[1:]
    if out and out[0].startswith("(") and out[0] != "(":
        out[0] = out[0].lstrip("(")
    for tok in out:
        if _is_assignment(tok):
            k, v = tok.split("=", 1)
            env[k] = v
        else:
            break
    return env


def _strip_git_global_opts(args: list) -> tuple:
    """Strip leading git global options (positioned between `git` and the
    subcommand verb): -C/--git-dir/--work-tree dir opts, `-c key=val` config
    overrides, and other `--flag[=x]` globals (--no-pager, --namespace=x, ...).

    Returns (remaining_args, dir_value, configs):
      dir_value  path passed to -C / --git-dir (repo resolution), or None
      configs    list of `-c` key=val strings, surfaced so the caller can deny
                 pushes carrying remote/transport overrides (was a silent full
                 bypass: `git -c anything push` previously classified as
                 not-push because the verb scan tripped on the `-c` token).
    """
    out = list(args)
    dir_value = None
    configs = []
    while out:
        tok = out[0]
        if tok in GIT_DIR_OPTS:
            if len(out) < 2:
                raise ParseError(f"dangling {tok} with no value")
            val = out[1]
            if tok in ("-C", "--git-dir"):
                dir_value = _accumulate_dir(dir_value, tok, val)
            out = out[2:]
            continue
        if tok in ("-c", "--config-env"):
            if len(out) < 2:
                raise ParseError(f"dangling {tok} with no value")
            configs.append(out[1])
            out = out[2:]
            continue
        if tok in GIT_VALUE_GLOBAL_FLAGS:
            # --namespace/--super-prefix/--attr-source consume their value;
            # stripping the pair keeps the flag's value from displacing the verb.
            if len(out) < 2:
                raise ParseError(f"dangling {tok} with no value")
            out = out[2:]
            continue
        if tok.startswith("--config-env="):
            configs.append(tok.split("=", 1)[1])
            out = out[1:]
            continue
        # --git-dir=foo style
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
        # Known no-value global flags consume only themselves; `--x=y` globals
        # likewise. An UNKNOWN bare `--flag` might take the next token as its
        # value (displacing the verb), so fail closed rather than guess.
        if tok.startswith("--"):
            if tok in GIT_BARE_GLOBAL_FLAGS or "=" in tok:
                out = out[1:]
                continue
            raise ParseError(f"unrecognized git global option {tok!r} before verb")
        break
    return out, dir_value, configs


def _is_remote_mutation(gargs: list) -> bool:
    """True if `gargs` (a git command with global opts already stripped) writes
    a remote's URL/transport config — i.e. a later same-command push would see
    the mutated remote while the identity check reads the stored one.

    Covers `git remote set-url|add ...` AND `git config <key> <value>` where
    <key> is a dangerous transport key (`git config remote.origin.url <x>` is
    exactly equivalent to `git remote set-url origin <x>` — a 2026-07 review).
    A `git config` READ (no value token, or `--get`) is NOT a mutation.
    """
    if not gargs:
        return False
    if gargs[0] == "remote":
        rest = [t for t in gargs[1:] if not t.startswith("-")]
        return bool(rest) and rest[0] in ("set-url", "add")
    if gargs[0] == "config":
        # A write needs key + value as positionals; --get/--list/-l are reads.
        if any(f in ("--get", "--get-all", "--get-regexp", "-l", "--list")
               for f in gargs[1:] if f.startswith("-")):
            return False
        pos = [t for t in gargs[1:] if not t.startswith("-")]
        return (
            len(pos) >= 2
            and pos[0].lower().startswith(DANGEROUS_GIT_CONFIG_PREFIXES)
        )
    return False


# ---- push-class classification ------------------------------------------

# env(1) options that consume the next token as a value.
ENV_VALUE_OPTS = {"-u", "--unset", "-C", "--chdir"}
ENV_BARE_OPTS = {"-i", "--ignore-environment", "-", "-v", "--debug", "-0", "--null"}

# `git -c key=val` keys (prefix-matched, case-insensitive) that reroute a push
# at runtime; presence on a push segment is a deny under threat model A.
DANGEROUS_GIT_CONFIG_PREFIXES = ("remote.", "url.", "http.", "credential.", "core.sshcommand")

# Env-var name prefixes that reroute git identity/transport; a leading
# assignment with one of these on a push segment is a deny.
DANGEROUS_ENV_PREFIXES = ("GIT_SSH", "GIT_CONFIG", "GIT_DIR", "GIT_WORK_TREE", "GIT_PROXY", "GIT_ALTERNATE")


def _strip_env_prefix(cmd: list, env: dict) -> list:
    """Strip leading `env [OPTS] [VAR=val...]` wrappers so `env git push`
    classifies as a push (must-fix #2). Assignments found after `env` are
    merged into `env` (caller's dict) so the dangerous-env check still sees
    them. `env -C dir` (GNU chdir) makes the effective cwd unknowable to a
    static parse -> ParseError (fail closed if the segment is push-ish).
    Unknown env options likewise raise rather than guess.
    """
    out = list(cmd)
    while out and _base(out[0]) == "env":
        out = out[1:]
        while out:
            tok = out[0]
            if _is_assignment(tok):
                k, v = tok.split("=", 1)
                env[k] = v
                out = out[1:]
                continue
            if tok in ("-C", "--chdir") or tok.startswith("--chdir="):
                raise ParseError("env --chdir before a command defeats cwd resolution")
            if tok in ENV_VALUE_OPTS:
                out = out[2:]
                continue
            if tok in ENV_BARE_OPTS or tok.startswith("--unset="):
                out = out[1:]
                continue
            if tok == "-S":
                # env -S '<string>' is expanded by expand_tokens; the inner
                # command is checked as its own segment. Stop here.
                return []
            if tok.startswith("-"):
                raise ParseError(f"unrecognized env option {tok!r} before command")
            break
    return out


def classify_segment(seg: list) -> dict | None:
    """Return a descriptor for a push-class segment, or None if not push-class.

    Descriptor keys:
      kind:        one of 'git-push', 'git-send-pack', 'gh-repo-create',
                   'gh-pr-create', 'gh-release-create', 'gh-pr-merge'
      dir:         value of -C/--git-dir if present, else None
      remote:      named remote for git-push (positional or --repo), else None
      url:         inline URL for git-send-pack, else None
      configs:     list of `git -c key=val` strings seen before the verb
      https_only:  True if this op is gh-CLI create or otherwise gh-state-relevant
      _env:        merged leading + post-`env` VAR=val assignments

    Raises ParseError if the segment is push-ish but unparseable.
    """
    env = collect_env_assigns(seg)
    cmd = _strip_prefix(seg)
    if not cmd:
        return None
    cmd = _strip_env_prefix(cmd, env)
    if not cmd:
        return None

    prog = _base(cmd[0])

    if prog == "git":
        args, dir_value, configs = _strip_git_global_opts(cmd[1:])
        if not args:
            return None
        verb = args[0]
        if verb == "push":
            # git push [options] [<remote>] [<refspec>...]
            remote = _parse_push_remote(args[1:])
            return {
                "kind": "git-push",
                "dir": dir_value,
                "remote": remote,
                "url": None,
                "configs": configs,
                "https_only": False,
                "_env": env,
            }
        if verb == "send-pack":
            # git send-pack [opts] <host:dir|url> <ref>... — push primitive
            # (must-fix #7). The destination is an inline URL, never a named
            # remote.
            url = _parse_send_pack_url(args[1:])
            return {
                "kind": "git-send-pack",
                "dir": dir_value,
                "remote": None,
                "url": url,
                "configs": configs,
                "https_only": False,
                "_env": env,
            }
        return None

    if prog == "gh":
        # gh has no -C-style global path opt we care about; subcommand follows.
        args = cmd[1:]
        if not args:
            return None
        sub = args[0]
        rest = args[1:]
        kind = None
        if sub == "repo" and rest and rest[0] == "create":
            # push-class only WITH --push or --source.
            flags = rest[1:]
            if _has_flag(flags, "--push") or _has_flag_with_value(flags, "--source"):
                kind = "gh-repo-create"
        elif sub == "pr" and rest and rest[0] == "create":
            kind = "gh-pr-create"
        elif sub == "pr" and rest and rest[0] == "merge":
            kind = "gh-pr-merge"
        elif sub == "release" and rest and rest[0] == "create":
            kind = "gh-release-create"
        if kind is None:
            return None
        return {
            "kind": kind,
            "dir": None,
            "remote": None,
            "url": None,
            "configs": [],
            "https_only": True,
            "_env": env,
        }

    return None


def _parse_push_remote(push_args: list) -> str | None:
    """Find the effective remote in `git push <args>`, else None (-> 'origin').

    The remote is the first non-option positional. `--repo <x>` / `--repo=<x>`
    is equivalent to the positional (must-fix #5); per git docs the positional
    takes precedence when both are given. Options that take a value
    (e.g. `-o <opt>`) are skipped with their value.
    """
    # Options to `git push` that consume the next token as their value.
    value_opts = {"-o", "--push-option", "--receive-pack", "--exec"}
    repo_opt = None
    i = 0
    n = len(push_args)
    while i < n:
        tok = push_args[i]
        if tok == "--":
            i += 1
            break
        if tok == "--repo":
            if i + 1 < n:
                repo_opt = push_args[i + 1]
            i += 2
            continue
        if tok.startswith("--repo="):
            repo_opt = tok.split("=", 1)[1]
            i += 1
            continue
        if tok.startswith("-"):
            if tok in value_opts:
                i += 2
                continue
            # `--opt=value` and bare flags consume only themselves.
            i += 1
            continue
        # First positional = remote (takes precedence over --repo).
        return tok
    return repo_opt


def _parse_send_pack_url(sp_args: list) -> str | None:
    """First non-option positional of `git send-pack` = destination URL/host:dir.

    Value-taking options are skipped with their value; returns None when no
    destination is found (caller denies — can't verify).
    """
    value_opts = {"--receive-pack", "--exec", "--remote"}
    i = 0
    n = len(sp_args)
    while i < n:
        tok = sp_args[i]
        if tok == "--":
            i += 1
            break
        if tok.startswith("-"):
            if tok in value_opts:
                i += 2
                continue
            i += 1
            continue
        return tok
    return None


def _has_flag(flags: list, name: str) -> bool:
    for f in flags:
        if f == name or f.startswith(name + "="):
            return True
    return False


def _has_flag_with_value(flags: list, name: str) -> bool:
    for i, f in enumerate(flags):
        if f == name and i + 1 < len(flags):
            return True
        if f.startswith(name + "="):
            return True
    return False


# ---- repo / identity resolution ------------------------------------------

def _git(args: list, cwd: str | None) -> tuple:
    """Run a read-only git command. Returns (rc, stdout-stripped)."""
    try:
        proc = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return proc.returncode, proc.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return 1, ""


def resolve_toplevel(repo_dir: str | None, cwd: str) -> str | None:
    base = repo_dir if repo_dir else cwd
    rc, top = _git(["-C", base, "rev-parse", "--show-toplevel"], cwd=None)
    if rc != 0 or not top:
        return None
    return top


def read_identity_tag(top: str) -> str | None:
    rc, val = _git(["-C", top, "config", "--local", "--get", "claude.identity"], cwd=None)
    if rc != 0 or not val:
        return None
    return val


def read_remote_url(top: str, remote: str) -> str | None:
    rc, url = _git(["-C", top, "remote", "get-url", remote], cwd=None)
    if rc != 0 or not url:
        return None
    return url


def read_git_user(top: str) -> tuple:
    _, name = _git(["-C", top, "config", "--get", "user.name"], cwd=None)
    _, email = _git(["-C", top, "config", "--get", "user.email"], cwd=None)
    return name, email


def gh_active_login() -> str | None:
    try:
        proc = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode != 0:
            return None
        return proc.stdout.strip() or None
    except (subprocess.SubprocessError, OSError):
        return None


# ---- remote URL parsing ---------------------------------------------------

def parse_remote_url(url: str) -> dict:
    """Classify a remote URL.

    Returns one of:
      {"scheme": "ssh",   "host": "<ssh-host-alias>"}
      {"scheme": "https", "owner": "<owner>"}
      {"scheme": "unknown"}
    """
    u = url.strip()
    # scp-like syntax: [user@]host:path  e.g. git@github.com-personal:foo/bar.git
    if u.startswith("git@") or (":" in u and "://" not in u and u.startswith("git@") is False and "@" in u.split(":", 1)[0]):
        # generic user@host:path
        before_colon = u.split(":", 1)[0]
        host = before_colon.split("@", 1)[-1]
        return {"scheme": "ssh", "host": host}
    # explicit ssh:// URL
    if u.startswith("ssh://"):
        rest = u[len("ssh://"):]
        authority = rest.split("/", 1)[0]
        host = authority.split("@", 1)[-1].split(":", 1)[0]
        return {"scheme": "ssh", "host": host}
    # https URL
    if u.startswith("https://") or u.startswith("http://"):
        rest = u.split("://", 1)[1]
        parts = rest.split("/")
        if len(parts) >= 2:
            host = parts[0].split("@", 1)[-1]
            owner = parts[1]
            if host in ("github.com", "www.github.com"):
                return {"scheme": "https", "owner": owner}
        return {"scheme": "unknown"}
    return {"scheme": "unknown"}


# ---- decision ------------------------------------------------------------

def load_map() -> dict:
    with open(MAP_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def deny(reason: str) -> int:
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    json.dump(out, sys.stdout)
    sys.stdout.flush()
    return 0


def _phyllis_state_dir() -> str:
    """Mirror hook-utils.sh hook_phyllis_state_dir(): honor HOOK_TEST_STATE_DIR
    so the test harness can isolate the audit log."""
    test_dir = os.environ.get("HOOK_TEST_STATE_DIR")
    if test_dir:
        return os.path.join(test_dir, "phyllis-state")
    return os.path.expanduser("~/.phyllis/state")


def _audit_override(message: str) -> None:
    """Best-effort audit-trail line to hook-errors.log, matching hook-utils.sh's
    line shape ([ts] <hook-name>: <LEVEL>: <message>). The hook-utils contract
    comment explicitly permits Python hooks to write the log directly with the
    same shape — preferred here over shelling out so the hook-name is correct
    (sourcing the lib under `bash -c` loses BASH_SOURCE[1] -> "unknown-hook")."""
    import datetime

    try:
        ts = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )
        line = f"[{ts}] gh-identity-guard.py: WARN: {message}\n"
        dir_ = _phyllis_state_dir()
        os.makedirs(dir_, exist_ok=True)
        with open(os.path.join(dir_, "hook-errors.log"), "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def _resolve_cd_target(cur: str | None, arg: str | None) -> str | None:
    """New effective cwd after a `cd`/`pushd` segment; None = unresolvable
    (tainted — a later push in the same command is denied)."""
    if cur is None:
        return None  # already tainted
    if arg is None:
        return os.path.expanduser("~")
    if arg.startswith("-"):
        return None  # `cd -` / option forms depend on shell state
    if "$" in arg or "`" in arg:
        return None  # unexpanded substitution — can't resolve statically
    return os.path.normpath(os.path.join(cur, os.path.expanduser(arg)))


def evaluate(command: str, cwd: str) -> int:
    try:
        tokens = shlex.split(command, comments=False, posix=True)
        # expand_tokens re-raises when a nested `bash -c '<shell>'` string is
        # itself unparseable — same treatment as a top-level parse failure
        # (fail closed on mutation shapes) instead of silently dropping the
        # subshell.
        tokens = expand_tokens(tokens)
    except ValueError:
        # Unparseable AND shaped like a real git-push/gh-create -> fail closed.
        # A bare "push" substring is NOT enough (it over-denied innocent Bash).
        if _PUSHY_ON_PARSE_FAIL.search(command):
            return deny(
                "Couldn't parse the command safely and it appears push-related. "
                "Re-run with a simpler form, ensure the repo is tagged "
                "(git config claude.identity <id>), and retry."
            )
        return 0

    segments = segment(tokens)

    # Walk segments IN ORDER, tracking state that affects later pushes:
    #   effective_cwd   updated by cd/pushd (None = unresolvable -> deny pushes)
    #   remote_mutated  set by `git remote set-url|add` (must-fix #4)
    # and collect EVERY push-class descriptor (must-fix #1 — previously only
    # the first was validated, so `git push A && git push B` skipped B).
    effective_cwd: str | None = cwd
    remote_mutated = False
    push_descriptors = []
    for seg in segments:
        stripped = _strip_prefix(seg)
        if stripped:
            base = _base(stripped[0])
            if base in ("cd", "pushd"):
                effective_cwd = _resolve_cd_target(
                    effective_cwd, stripped[1] if len(stripped) > 1 else None
                )
                continue
            if base == "popd":
                effective_cwd = None  # shell dir-stack state — can't track
                continue
            if base == "git":
                # Detect a remote mutation that would make a later push in the
                # same command validate the PRE-mutation URL. Strip git global
                # opts first (via the real parser) so a two-token option before
                # the verb — `git -C dir remote set-url ...` — can't hide the
                # `remote` token behind the option's value (a 2026-07 review).
                try:
                    gargs, _gd, _cfgs = _strip_git_global_opts(stripped[1:])
                except ParseError:
                    gargs = []
                if _is_remote_mutation(gargs):
                    remote_mutated = True
                    continue
        try:
            desc = classify_segment(seg)
        except ParseError as exc:
            # Push-ish but unparseable -> only fail closed if it really looks
            # push-class (starts with git push / gh repo create / gh pr|release).
            joined = " ".join(seg)
            if "push" in joined or "send-pack" in joined or (
                "gh" in joined and "create" in joined
            ):
                return deny(
                    f"Couldn't parse a push command safely ({joined!r}: {exc}). "
                    "Retry with a simpler invocation (no env/option tricks "
                    "before the verb)."
                )
            continue
        if desc is not None:
            desc["_cwd"] = effective_cwd
            desc["_remote_mutated"] = remote_mutated
            push_descriptors.append(desc)

    if not push_descriptors:
        return 0  # allow — no push-class command

    try:
        idmap = load_map()
    except (OSError, json.JSONDecodeError) as exc:
        return deny(
            f"Identity map unreadable ({exc}); refusing push until "
            f"{MAP_PATH} is valid."
        )
    identities = idmap.get("identities", {})

    for desc in push_descriptors:
        reason = _check_descriptor(desc, identities)
        if reason is not None:
            return deny(reason)
    return 0  # allow — every push-class segment validated


def _check_descriptor(desc: dict, identities: dict) -> str | None:
    """Validate one push-class descriptor. Returns a deny reason, or None."""
    env = desc["_env"]
    override = env.get("CLAUDE_IDENTITY_OVERRIDE")
    supplied = env.get("CLAUDE_IDENTITY")

    # Transport/identity-rerouting env vars on a push segment (ADV-6/7/8
    # mitigation): the static checks below validate the STORED remote config,
    # which these vars override at runtime. Deny rather than validate a lie.
    for key in env:
        if key.upper().startswith(DANGEROUS_ENV_PREFIXES):
            return (
                f"Push with {key}=... set: that env var can reroute the push "
                "past the identity checks. Run the push without it."
            )
    for cfg in desc.get("configs", []):
        cfg_key = cfg.split("=", 1)[0].strip().lower()
        if cfg_key.startswith(DANGEROUS_GIT_CONFIG_PREFIXES):
            return (
                f"Push with `git -c {cfg_key}=...`: that config override can "
                "reroute the push past the identity checks. Run the push "
                "without it."
            )

    if desc["_remote_mutated"]:
        return (
            "A `git remote set-url|add` precedes this push in the same "
            "command, so the identity checks would validate the pre-mutation "
            "URL. Run the remote change and the push as separate commands."
        )
    if desc["_cwd"] is None and desc["dir"] is None:
        return (
            "A `cd`/`pushd`/`popd` earlier in this command made the working "
            "directory unresolvable, so the push repo can't be verified. "
            "Run the push as its own command or use `git -C <dir> push`."
        )

    # Resolve repo top-level. For gh repo create the repo dir may not exist yet
    # (brand-new repo); allow CLAUDE_IDENTITY to supply identity in that case.
    top = resolve_toplevel(desc["dir"], desc["_cwd"])

    if top is None:
        # No git repo. Only gh-repo-create is legitimate here.
        if desc["kind"] == "gh-repo-create":
            chosen = supplied or override
            if not chosen:
                return (
                    "gh repo create outside a tagged repo: set the identity "
                    "explicitly, e.g. CLAUDE_IDENTITY=<PropterMalone|your-personal-account> "
                    "gh repo create ... (then the new repo should be tagged "
                    "with git config claude.identity <id>)."
                )
            return _check_identity_policy_and_ghstate(
                chosen, desc, identities, top=None
            )
        return (
            "Push-class command but no git repository found at "
            f"{desc['dir'] or desc['_cwd']}. Run inside the repo (or pass -C <dir>)."
        )

    # Read the per-repo tag.
    tag = read_identity_tag(top)

    if tag is None:
        if override:
            _audit_override(
                f"CLAUDE_IDENTITY_OVERRIDE={override} used to bypass untagged "
                f"block on {top} (kind={desc['kind']})"
            )
            tag = override
        else:
            return (
                f"Repo not tagged. Run: git -C {top} config claude.identity "
                "<PropterMalone|your-personal-account|local-only>  (then retry the push). "
                "If you must bypass once, prefix CLAUDE_IDENTITY_OVERRIDE=<id> "
                "— it still enforces the host/gh-account checks."
            )

    return _check_identity_policy_and_ghstate(tag, desc, identities, top=top)


def _check_identity_policy_and_ghstate(
    tag: str, desc: dict, identities: dict, top: str | None
) -> str | None:
    entry = identities.get(tag)
    if entry is None:
        return (
            f"Identity tag {tag!r} is not in the identity map "
            f"({MAP_PATH}). Re-tag with a known id "
            "(PropterMalone | your-personal-account | local-only)."
        )

    # Policy gates.
    if entry.get("retired") is True:
        return (
            f"Identity {tag!r} is RETIRED (pushes blocked). "
            f"Re-tag the repo with an active identity: "
            f"git -C {top or '<repo>'} config claude.identity "
            "<PropterMalone|your-personal-account>."
        )
    if entry.get("push") is False:
        note = entry.get("note", "")
        return (
            f"Identity {tag!r} has push disabled by policy"
            + (f" ({note})" if note else "")
            + ". Re-tag with a push-enabled identity to push: "
            f"git -C {top or '<repo>'} config claude.identity "
            "<PropterMalone|your-personal-account>."
        )

    expected_ssh_host = entry.get("ssh_host")
    expected_gh = entry.get("gh_account")

    # Primary check: remote URL identity (SSH host or HTTPS owner).
    is_https_push = False
    if desc["kind"] == "git-send-pack":
        # Inline destination URL — never a named remote (must-fix #7).
        url = desc.get("url")
        if not url:
            return (
                "git send-pack with no parseable destination URL — cannot "
                "verify push identity. Use `git push` with a named remote."
            )
        parsed = parse_remote_url(url)
        if parsed["scheme"] == "ssh":
            if parsed["host"] != expected_ssh_host:
                return (
                    f"send-pack identity mismatch. Repo tagged {tag!r} "
                    f"(expects SSH host {expected_ssh_host!r}) but destination "
                    f"host is {parsed['host']!r} (url: {url})."
                )
        else:
            return (
                f"Unrecognized send-pack destination {url!r} — cannot verify "
                "push identity. Use `git push` with a named remote."
            )
    elif desc["kind"] == "git-push" and top is not None:
        remote = desc["remote"] or "origin"
        url = read_remote_url(top, remote)
        if url is None:
            return (
                f"Could not read URL for remote {remote!r} in {top}. "
                "Add/verify the remote and retry."
            )
        parsed = parse_remote_url(url)
        if parsed["scheme"] == "ssh":
            if parsed["host"] != expected_ssh_host:
                return (
                    f"Push identity mismatch. Repo tagged {tag!r} "
                    f"(expects SSH host {expected_ssh_host!r}) but remote "
                    f"{remote!r} points at host {parsed['host']!r} "
                    f"(url: {url}). Fix the remote URL or the tag before pushing."
                )
        elif parsed["scheme"] == "https":
            is_https_push = True
            if parsed["owner"] != expected_gh:
                return (
                    f"Push identity mismatch. Repo tagged {tag!r} "
                    f"(expects owner {expected_gh!r}) but HTTPS remote "
                    f"{remote!r} owner is {parsed['owner']!r} (url: {url})."
                )
        else:
            return (
                f"Unrecognized remote URL for {remote!r}: {url!r}. "
                "Cannot verify push identity — refusing. Use a github.com SSH "
                "host-alias or https://github.com/<owner>/... remote."
            )

    # gh-state check: only for gh-CLI create ops or HTTPS push.
    needs_gh_state = bool(desc.get("https_only")) or is_https_push
    if needs_gh_state:
        active = gh_active_login()
        if active is None:
            return (
                "Could not determine the active gh account "
                "(gh api user failed). Run `gh auth status` / "
                f"`gh auth switch --user {expected_gh}` and retry."
            )
        if active != expected_gh:
            return (
                f"gh account mismatch. Repo tagged {tag!r} expects gh account "
                f"{expected_gh!r} but the active gh login is {active!r}. "
                f"Run: gh auth switch --user {expected_gh}  (then retry). "
                "This hook will not switch for you."
            )

    return None  # allow


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
    except Exception as exc:  # noqa: BLE001 — fail closed on any internal error.
        # Only escalate to a deny if this really looked push-related; otherwise
        # never break unrelated Bash commands (tight shape test, not bare "push").
        if _PUSHY_ON_PARSE_FAIL.search(cmd):
            return deny(
                f"Internal error while validating push identity ({exc}). "
                "Refusing to allow an unverified push. Re-run after tagging "
                "the repo (git config claude.identity <id>)."
            )
        return 0


if __name__ == "__main__":
    sys.exit(main())
