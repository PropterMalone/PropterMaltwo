#!/usr/bin/env bash
# test-gh-identity.sh — STANDALONE test runner for the GitHub-identity hooks:
#   gh-identity-guard.py        (push validator)
#   gh-commit-author-guard.py   (commit-author validator)
#
# Kept separate from test-hooks.sh so neither hook auto-runs until a reviewer
# wires them into settings.json.
#
# Strategy: real hooks need a real tagged git repo, so we create THROWAWAY
# repos under a tempdir and never touch ~/Projects. Remotes are faked with
# `git remote add` to the various host-aliases. claude.identity is set per-repo.
#
# gh-state guard: the SSH push path only calls `gh api user` for HTTPS remotes
# or gh-CLI create ops. Every SSH-remote case here therefore makes NO network
# call. We do not exercise live `gh repo create`/HTTPS-push (would hit the real
# gh state and the network); those paths are covered by reasoning + the parse
# layer is unit-tested via the classify cases.
#
# Each hook reads a JSON envelope on stdin: {"tool_input":{"command":"...","cwd":"..."}}
# A DENY => stdout contains permissionDecision":"deny". An ALLOW => empty stdout.
#
# Usage:  bash ~/.claude/hooks/test-gh-identity.sh
#         VERBOSE=1 bash ~/.claude/hooks/test-gh-identity.sh
#         KEEP_TEST_DIR=1 ... (keep the sandbox for inspection)
#
# Exits 0 on all pass, 1 on any failure.

set -u

HOOKS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PUSH_HOOK="$HOOKS_DIR/gh-identity-guard.py"
COMMIT_HOOK="$HOOKS_DIR/gh-commit-author-guard.py"

for h in "$PUSH_HOOK" "$COMMIT_HOOK"; do
  if [ ! -f "$h" ]; then
    printf 'FAIL: hook missing: %s\n' "$h" >&2
    exit 1
  fi
done

TEST_DIR="$(mktemp -d -t gh-identity-test-XXXXXX)"

# Self-contained fixture identity map — the guards read it via
# CLAUDE_GH_IDENTITY_MAP, so this suite never depends on (or leaks into)
# the operator's real ~/.claude/github-identity-map.json.
cat > "$TEST_DIR/identity-map.json" <<'MAPEOF'
{
  "identities": {
    "PropterMalone": {
      "gh_account": "PropterMalone", "ssh_host": "github.com",
      "user_name": "PropterMalone",
      "user_email": "proptermalone@users.noreply.github.com",
      "push": true, "retired": false
    },
    "your-personal-account": {
      "gh_account": "your-personal-account", "ssh_host": "github.com-personal",
      "user_name": "Pat Personal", "user_email": "pat@personal.example",
      "push": true, "retired": false
    },
    "RetiredAccount": {
      "gh_account": "RetiredAccount", "ssh_host": "github.com-retiredaccount",
      "user_name": "RetiredAccount", "user_email": "retired@personal.example",
      "push": true, "retired": true
    },
    "local-only": { "push": false, "retired": false }
  }
}
MAPEOF
export CLAUDE_GH_IDENTITY_MAP="$TEST_DIR/identity-map.json"
# Isolate git config so the host's global user.name/email never leaks in.
export HOME_REAL="$HOME"
export GIT_CONFIG_GLOBAL="$TEST_DIR/gitconfig-global"
export GIT_CONFIG_SYSTEM="/dev/null"
: > "$GIT_CONFIG_GLOBAL"
# Identity-guard reads the map via ~/.claude — keep HOME pointing at the real
# home so the production map + hook-utils resolve. (We override only git config
# locations, not HOME.)

cleanup() {
  if [ -z "${KEEP_TEST_DIR:-}" ]; then
    rm -rf "$TEST_DIR"
  else
    printf 'kept test dir: %s\n' "$TEST_DIR" >&2
  fi
}
trap cleanup EXIT

PASS=0
FAIL=0
FAIL_NAMES=()

# make_repo <name> [identity] [remote-url] [user.name] [user.email]
# Creates a throwaway repo and echoes its absolute path.
make_repo() {
  local name="$1" identity="${2:-}" remote="${3:-}" uname="${4:-}" uemail="${5:-}"
  local dir="$TEST_DIR/$name"
  mkdir -p "$dir"
  git -C "$dir" init -q
  if [ -n "$identity" ]; then
    git -C "$dir" config claude.identity "$identity"
  fi
  if [ -n "$remote" ]; then
    git -C "$dir" remote add origin "$remote"
  fi
  if [ -n "$uname" ]; then
    git -C "$dir" config user.name "$uname"
  fi
  if [ -n "$uemail" ]; then
    git -C "$dir" config user.email "$uemail"
  fi
  printf '%s\n' "$dir"
}

# envelope <command> <cwd>  -> JSON on stdout
envelope() {
  python3 - "$1" "$2" <<'PY'
import json, sys
print(json.dumps({"tool_input": {"command": sys.argv[1], "cwd": sys.argv[2]}}))
PY
}

# expect <name> <hook> <command> <cwd> <deny|allow>
expect() {
  local name="$1" hook="$2" command="$3" cwd="$4" want="$5"
  local out rc
  out="$(envelope "$command" "$cwd" | python3 "$hook" 2>"$TEST_DIR"/stderr-capture)"
  rc=$?
  local got
  if printf '%s' "$out" | grep -q '"permissionDecision":[[:space:]]*"deny"' \
     || printf '%s' "$out" | grep -q '"permissionDecision": "deny"'; then
    got="deny"
  elif [ -z "$out" ]; then
    got="allow"
  else
    got="other"
  fi

  local fail=""
  if [ "$rc" -ne 0 ]; then
    fail="exit=$rc"
  fi
  if [ "$got" != "$want" ]; then
    fail="${fail:+$fail,}got=$got want=$want"
  fi

  if [ -z "$fail" ]; then
    printf '  PASS %-46s\n' "$name"
    PASS=$((PASS + 1))
  else
    printf '  FAIL %-46s [%s]\n' "$name" "$fail"
    if [ -n "${VERBOSE:-}" ] || [ "$got" = "other" ]; then
      printf '    cmd:    %s\n' "$command"
      printf '    stdout: %s\n' "$(printf '%s' "$out" | head -c 400 | tr '\n' ' ')"
      printf '    stderr: %s\n' "$(head -c 300 "$TEST_DIR"/stderr-capture 2>/dev/null | tr '\n' ' ')"
    fi
    FAIL=$((FAIL + 1))
    FAIL_NAMES+=("$name")
  fi
  rm -f ""$TEST_DIR"/stderr-capture"
}

printf 'gh-identity hook tests — sandbox=%s\n' "$TEST_DIR"
printf '%s\n' "----"

# ---- Repos -----------------------------------------------------------------
# PropterMalone repo, correct SSH host (github.com).
R_PROPTER="$(make_repo propter PropterMalone \
  "git@github.com:PropterMalone/foo.git" \
  "PropterMalone" "proptermalone@users.noreply.github.com")"

# your-personal-account repo, correct SSH host (github.com-personal).
R_PAT="$(make_repo pat your-personal-account \
  "git@github.com-personal:foo/bar.git" \
  "Pat Personal" "pat@personal.example")"

# Tagged PropterMalone but remote points at your-personal-account host -> mismatch.
R_MISMATCH="$(make_repo mismatch PropterMalone \
  "git@github.com-personal:foo/bar.git" \
  "PropterMalone" "proptermalone@users.noreply.github.com")"

# Untagged repo with a (correct-looking) remote.
R_UNTAGGED="$(make_repo untagged "" \
  "git@github.com:PropterMalone/foo.git")"

# local-only tag.
R_LOCAL="$(make_repo localonly local-only \
  "git@github.com:PropterMalone/foo.git")"

# RetiredAccount (retired) tag.
R_RETIRED="$(make_repo retiredaccount RetiredAccount \
  "git@github.com-retiredaccount:foo/bar.git")"

# Named-remote repo: origin is wrong host, 'upstream' is the correct pat host.
R_NAMED="$(make_repo named your-personal-account \
  "git@github.com:PropterMalone/foo.git" \
  "Pat Personal" "pat@personal.example")"
git -C "$R_NAMED" remote add upstream "git@github.com-personal:foo/bar.git"

# Commit-author mismatch repo: tagged your-personal-account but author is PropterMalone.
R_COMMIT_BAD="$(make_repo commitbad your-personal-account \
  "git@github.com-personal:foo/bar.git" \
  "PropterMalone" "proptermalone@users.noreply.github.com")"

# Commit-author good repo: tagged your-personal-account, author matches.
R_COMMIT_OK="$(make_repo commitok your-personal-account \
  "git@github.com-personal:foo/bar.git" \
  "Pat Personal" "pat@personal.example")"

# Untagged repo for commit hook (should allow).
R_COMMIT_UNTAGGED="$(make_repo commituntagged "" "")"

# ---- PUSH HOOK cases -------------------------------------------------------

# untagged -> deny
expect "push/untagged->deny" "$PUSH_HOOK" \
  "git push" "$R_UNTAGGED" "deny"

# correct host -> allow
expect "push/correct-host->allow" "$PUSH_HOOK" \
  "git push" "$R_PROPTER" "allow"

expect "push/correct-host-pat->allow" "$PUSH_HOOK" \
  "git push origin main" "$R_PAT" "allow"

# host mismatch (tag PropterMalone, remote your-personal-account host) -> deny
expect "push/host-mismatch->deny" "$PUSH_HOOK" \
  "git push" "$R_MISMATCH" "deny"

# local-only -> deny
expect "push/local-only->deny" "$PUSH_HOOK" \
  "git push" "$R_LOCAL" "deny"

# RetiredAccount retired -> deny
expect "push/retiredaccount-retired->deny" "$PUSH_HOOK" \
  "git push" "$R_RETIRED" "deny"

# git -C <dir> push (cwd elsewhere) -> resolved via -C -> allow
expect "push/git-C-dir->allow" "$PUSH_HOOK" \
  "git -C $R_PROPTER push" "$TEST_DIR" "allow"

# git -C <dir> push to a mismatch repo -> deny
expect "push/git-C-dir-mismatch->deny" "$PUSH_HOOK" \
  "git -C $R_MISMATCH push" "$TEST_DIR" "deny"

# bash -c 'git push' (expand_tokens path) -> allow (correct host)
expect "push/bash-c-correct->allow" "$PUSH_HOOK" \
  "bash -c 'git push'" "$R_PROPTER" "allow"

# bash -c 'git push' on mismatch repo -> deny
expect "push/bash-c-mismatch->deny" "$PUSH_HOOK" \
  "bash -c 'git push'" "$R_MISMATCH" "deny"

# named remote: push to 'upstream' (correct pat host) on a repo whose origin
# is the wrong host -> allow (we check the NAMED remote, not origin).
expect "push/named-remote-correct->allow" "$PUSH_HOOK" \
  "git push upstream main" "$R_NAMED" "allow"

# named remote: push to 'origin' (wrong host) explicitly -> deny.
expect "push/named-remote-origin-wrong->deny" "$PUSH_HOOK" \
  "git push origin main" "$R_NAMED" "deny"

# git fetch -> allow (not push-class)
expect "push/git-fetch->allow" "$PUSH_HOOK" \
  "git fetch origin" "$R_MISMATCH" "allow"

# git status / log / diff -> allow
expect "push/git-status->allow" "$PUSH_HOOK" \
  "git status" "$R_MISMATCH" "allow"

# literal word push inside a commit -m message -> allow (commit isn't push-class)
expect "push/commit-with-push-in-msg->allow" "$PUSH_HOOK" \
  "git commit -m 'push the button later'" "$R_MISMATCH" "allow"

# echo with the word push -> allow
expect "push/echo-push->allow" "$PUSH_HOOK" \
  "echo do not push this" "$R_MISMATCH" "allow"

# gh repo view -> allow (read-only)
expect "push/gh-repo-view->allow" "$PUSH_HOOK" \
  "gh repo view" "$R_PROPTER" "allow"

# gh pr list -> allow
expect "push/gh-pr-list->allow" "$PUSH_HOOK" \
  "gh pr list" "$R_PROPTER" "allow"

# gh repo create WITHOUT --push/--source -> allow (not push-class)
expect "push/gh-repo-create-nopush->allow" "$PUSH_HOOK" \
  "gh repo create foo --private" "$R_PROPTER" "allow"

# parse-fail: unbalanced quote with a push verb -> deny (fail-closed)
expect "push/parse-fail->deny" "$PUSH_HOOK" \
  "git push origin 'unterminated" "$R_PROPTER" "deny"

# CLAUDE_IDENTITY_OVERRIDE bypasses untagged block but still checks host:
#   override=PropterMalone on untagged repo with correct PropterMalone host -> allow
expect "push/override-correct-host->allow" "$PUSH_HOOK" \
  "CLAUDE_IDENTITY_OVERRIDE=PropterMalone git push" "$R_UNTAGGED" "allow"

#   override=your-personal-account on untagged repo whose remote is PropterMalone host -> deny (host check still runs)
expect "push/override-wrong-host->deny" "$PUSH_HOOK" \
  "CLAUDE_IDENTITY_OVERRIDE=your-personal-account git push" "$R_UNTAGGED" "deny"

# ---- COMMIT HOOK cases -----------------------------------------------------

# commit author mismatch -> deny
expect "commit/author-mismatch->deny" "$COMMIT_HOOK" \
  "git commit -m 'msg'" "$R_COMMIT_BAD" "deny"

# commit author OK -> allow
expect "commit/author-ok->allow" "$COMMIT_HOOK" \
  "git commit -m 'msg'" "$R_COMMIT_OK" "allow"

# commit with literal word push in message, author OK -> allow
expect "commit/push-in-msg-ok->allow" "$COMMIT_HOOK" \
  "git commit -m 'push the button'" "$R_COMMIT_OK" "allow"

# commit with literal push in message, author MISMATCH -> deny
expect "commit/push-in-msg-mismatch->deny" "$COMMIT_HOOK" \
  "git commit -m 'push the button'" "$R_COMMIT_BAD" "deny"

# bash -c 'git commit' author mismatch -> deny (expand_tokens path)
expect "commit/bash-c-mismatch->deny" "$COMMIT_HOOK" \
  "bash -c \"git commit -m msg\"" "$R_COMMIT_BAD" "deny"

# git -C <dir> commit author mismatch -> deny
expect "commit/git-C-mismatch->deny" "$COMMIT_HOOK" \
  "git -C $R_COMMIT_BAD commit -m msg" "$TEST_DIR" "deny"

# commit --dry-run -> allow even on mismatch repo
expect "commit/dry-run->allow" "$COMMIT_HOOK" \
  "git commit --dry-run -m msg" "$R_COMMIT_BAD" "allow"

# untagged repo commit -> allow (too noisy to block)
expect "commit/untagged->allow" "$COMMIT_HOOK" \
  "git commit -m msg" "$R_COMMIT_UNTAGGED" "allow"

# git status (not commit) on mismatch repo -> allow
expect "commit/git-status->allow" "$COMMIT_HOOK" \
  "git status" "$R_COMMIT_BAD" "allow"

# commit hook ignores push commands entirely -> allow
expect "commit/push-ignored->allow" "$COMMIT_HOOK" \
  "git push" "$R_MISMATCH" "allow"

printf '%s\n' "----"
printf 'pass=%d fail=%d\n' "$PASS" "$FAIL"
if [ "$FAIL" -gt 0 ]; then
  printf 'failed: %s\n' "${FAIL_NAMES[*]}"
  exit 1
fi
exit 0
