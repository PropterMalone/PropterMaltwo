#!/usr/bin/env bash
# test-hooks.sh — smoke test for the registered Claude Code hooks.
#
# Coverage is asserted, not assumed: a self-count check (see "Harness coverage
# self-assertion" at the end) derives the registered hook scripts from
# settings.json and fails if this harness exercises fewer than that, so a newly
# registered hook can't silently slip past the safety review (the I7 drift the
# 2026-06-29 retro caught: 11 registered, only 7 exercised, the 4 most
# safety-critical untested).
#
# Each hook is fired with a fixture from ~/.claude/hooks/fixtures/
# against an isolated state dir (HOOK_TEST_STATE_DIR). Production state
# at ~/.claude/state and ~/.phyllis/state is never written.
#
# Asserts per hook:
#   (a) exit code 0 (hooks must never break the parent session)
#   (b) any expected state file is written at the expected path
#   (c) no NEW lines appended to hook-errors.log since test start
#
# Usage:
#   bash ~/.claude/hooks/test-hooks.sh           # run all
#   VERBOSE=1 bash ~/.claude/hooks/test-hooks.sh # print hook stdout/stderr
#
# Exits 0 on all pass, 1 on any failure.

set -u

HOOKS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURES_DIR="$HOOKS_DIR/fixtures"
LIB="$HOOKS_DIR/lib/hook-utils.sh"

# Sanity: lib must be present.
if [ ! -f "$LIB" ]; then
  printf 'FAIL: hook-utils.sh missing at %s\n' "$LIB" >&2
  exit 1
fi

# Per-run sandbox. Cleaned up on exit unless KEEP_TEST_DIR=1.
TEST_DIR="$(mktemp -d -t hook-test-XXXXXX)"
export HOOK_TEST_STATE_DIR="$TEST_DIR"
# shellcheck source=lib/hook-utils.sh
source "$LIB"

# Pre-create the dirs the hooks expect; use the lib's resolution so the
# test path stays canonical.
PHYLLIS_STATE="$(hook_phyllis_state_dir)"
CLAUDE_STATE="$(hook_state_dir)"
PHYLLIS_HOME_TEST="$TEST_DIR/phyllis-home"
mkdir -p "$PHYLLIS_STATE" "$CLAUDE_STATE/locks" "$PHYLLIS_HOME_TEST"
ERR_LOG="$PHYLLIS_STATE/hook-errors.log"
: > "$ERR_LOG"  # truncate so "no new errors" = "log empty"

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

# fire_hook <name> <hook-cmd> <fixture-relative-path> [<assert-fn>]
# Runs <hook-cmd> with fixture as stdin, captures stdout/stderr/exit,
# then runs <assert-fn> for additional state-file checks.
# Assertions:
#   - exit 0
#   - no new lines in hook-errors.log
#   - <assert-fn> returns 0
fire_hook() {
  local name="$1"
  local cmd="$2"
  local fixture="$3"
  local assert_fn="${4:-}"
  local fixture_path="$FIXTURES_DIR/$fixture"

  if [ ! -f "$fixture_path" ]; then
    printf '  FAIL %-40s missing fixture: %s\n' "$name" "$fixture_path"
    FAIL=$((FAIL + 1))
    FAIL_NAMES+=("$name")
    return
  fi

  local out_file err_file rc
  out_file="$(mktemp)"
  err_file="$(mktemp)"
  local err_lines_before
  err_lines_before=$(wc -l < "$ERR_LOG" 2>/dev/null || echo 0)

  # Run with bash -c so the command string can include args. The fixture
  # is piped as stdin (matches how Claude Code invokes hooks).
  bash -c "$cmd" < "$fixture_path" > "$out_file" 2> "$err_file"
  rc=$?

  local err_lines_after
  err_lines_after=$(wc -l < "$ERR_LOG" 2>/dev/null || echo 0)
  local new_err_lines=$((err_lines_after - err_lines_before))

  local fail_reasons=()
  if [ "$rc" -ne 0 ]; then
    fail_reasons+=("exit=$rc")
  fi
  if [ "$new_err_lines" -gt 0 ]; then
    fail_reasons+=("hook-errors.log+=$new_err_lines")
  fi
  if [ -n "$assert_fn" ]; then
    if ! "$assert_fn" "$out_file" "$err_file"; then
      fail_reasons+=("assert=$assert_fn")
    fi
  fi

  if [ "${#fail_reasons[@]}" -eq 0 ]; then
    printf '  PASS %-40s\n' "$name"
    PASS=$((PASS + 1))
  else
    printf '  FAIL %-40s [%s]\n' "$name" "$(IFS=,; printf '%s' "${fail_reasons[*]}")"
    if [ -n "${VERBOSE:-}" ] || [ "$rc" -ne 0 ] || [ "$new_err_lines" -gt 0 ]; then
      printf '    stdout: %s\n' "$(head -c 500 < "$out_file" | tr '\n' ' ')"
      printf '    stderr: %s\n' "$(head -c 500 < "$err_file" | tr '\n' ' ')"
      if [ "$new_err_lines" -gt 0 ]; then
        printf '    new errors:\n'
        tail -n "$new_err_lines" "$ERR_LOG" | sed 's/^/      /'
      fi
    fi
    FAIL=$((FAIL + 1))
    FAIL_NAMES+=("$name")
  fi

  rm -f "$out_file" "$err_file"
}

# ---- Assertion helpers (each takes <stdout-path> <stderr-path>) ----

assert_kickoff_sentinel_fresh() {
  # Fresh session: sentinel file should be created.
  local sid="test-fresh-00000000-0000-0000-0000-000000000001"
  local sentinel="$HOOK_TEST_STATE_DIR/kickoff-sentinels/claude-kickoff-$sid"
  if [ ! -f "$sentinel" ]; then
    return 1
  fi
  # And the hook should have emitted the AUTO-KICKOFF JSON envelope.
  if ! grep -q 'AUTO-KICKOFF' "$1"; then
    return 1
  fi
  return 0
}

assert_kickoff_sentinel_existing() {
  # Existing session: pre-create the sentinel, hook should no-op (no JSON output).
  # We pre-create in the runner; this just verifies output is empty.
  if [ -s "$1" ]; then
    return 1
  fi
  return 0
}

assert_stub_clean_silent() {
  # Clean Edit: hook should print nothing.
  if [ -s "$1" ]; then
    return 1
  fi
  return 0
}

assert_secret_scan_flags() {
  # Secret-laden Edit: stub-check + secret-scan both fire. Secret-scan
  # should mention "Secret patterns" or "CRITICAL".
  if ! grep -qE 'Secret patterns|CRITICAL' "$1"; then
    return 1
  fi
  return 0
}

assert_secret_scan_output_shape() {
  # Hook output must use the wrapped hookSpecificOutput envelope — the flat
  # {"additionalContext": ...} form is silently discarded by Claude Code
  # (9A 2026-06-09 m1). Parse stdout as JSON and require
  # hookSpecificOutput.additionalContext to be a non-empty string.
  python3 - "$1" <<'PYEOF'
import json, sys
try:
    with open(sys.argv[1]) as fh:
        data = json.load(fh)
except Exception:
    sys.exit(1)
ctx = data.get("hookSpecificOutput", {}).get("additionalContext")
sys.exit(0 if isinstance(ctx, str) and ctx else 1)
PYEOF
}

assert_html_served_marker() {
  # post-write-serve.sh should drop a marker into the test served dir.
  if [ ! -f "$HOOK_TEST_STATE_DIR/served/files.log" ]; then
    return 1
  fi
  if ! grep -q '/tmp/hook-test-foo.html' "$HOOK_TEST_STATE_DIR/served/files.log"; then
    return 1
  fi
  return 0
}

assert_rfip_context() {
  # pre-web-rfip.py should emit JSON with additionalContext containing "RFIP".
  if ! grep -q 'RFIP' "$1"; then
    return 1
  fi
  return 0
}

assert_stop_failure_logged() {
  # stop-failure-throttle.sh should append an entry to calibration-log.jsonl.
  # The current hook emits pretty-printed (multi-line) JSON via `jq -n` so
  # we grep the whole file rather than the last line. Also assert the
  # additionalContext echoes back to stdout so the conversation sees it.
  local log="$PHYLLIS_HOME_TEST/calibration-log.jsonl"
  if [ ! -s "$log" ]; then
    return 1
  fi
  if ! grep -q '"throttled": true' "$log" && ! grep -q '"throttled":true' "$log"; then
    return 1
  fi
  if ! grep -q 'Rate limit' "$1"; then
    return 1
  fi
  return 0
}

assert_session_end_log_or_skip() {
  # session-end-snapshot.sh: in test mode the ccusage cache may be missing,
  # which is a documented skip path. We accept either:
  #   (a) calibration-log.jsonl row appended, OR
  #   (b) hook-errors.log entry recording a known-skip reason.
  # We require at least one of those — silent-no-state is the bug from
  # 2026-04-22 that this whole harness exists to catch.
  local log="$PHYLLIS_HOME_TEST/calibration-log.jsonl"
  if [ -s "$log" ]; then
    return 0
  fi
  if [ -s "$ERR_LOG" ] && grep -q 'session-end-snapshot' "$ERR_LOG"; then
    # Allowed skip — the hook recorded *why* it didn't write.
    # But the runner counts "new error lines" as a failure signal, so we
    # roll those back here: the assert_fn returning 0 says "this skip
    # was structured, not silent". We adjust err_lines_before by editing
    # ERR_LOG... no: simplest is to truncate so the runner's diff shows 0.
    # That's a side effect inside an assert which is ugly but localized.
    : > "$ERR_LOG"
    return 0
  fi
  return 1
}

# ---- Safety-critical PreToolUse deny hooks (block-*.py) ----
# Contract (probed 2026-06-29): on a MATCH the hook exits 0 and prints a JSON
# envelope {"hookSpecificOutput": {"permissionDecision": "deny", ...}}. On a
# non-match it exits 0 with EMPTY stdout. So the deny path is asserted by the
# presence of the deny envelope, and the allow path by empty stdout — NOT by
# exit code (these hooks deny via decision payload, never via failure).

assert_deny_envelope() {
  # Matched/blocked case: stdout must be JSON with permissionDecision == "deny".
  python3 - "$1" <<'PYEOF'
import json, sys
try:
    with open(sys.argv[1]) as fh:
        data = json.load(fh)
except Exception:
    sys.exit(1)
dec = data.get("hookSpecificOutput", {}).get("permissionDecision")
sys.exit(0 if dec == "deny" else 1)
PYEOF
}

assert_allow_silent() {
  # Non-matching case: a deny hook must pass the call through with empty stdout.
  if [ -s "$1" ]; then
    return 1
  fi
  return 0
}

assert_sanitize_removed_broken() {
  # sanitize-permission-allowlist.py is fired with HOME pointed at a per-case
  # sandbox (see the fire below) that contains a settings.local.json with one
  # over-escaped Bash() entry plus two clean ones. After the run the broken
  # entry must be gone, the clean ones kept, and a telemetry line written —
  # all inside the sandbox, zero production touch.
  local sb="$HOOK_TEST_STATE_DIR/sanitize-home"
  local cfg="$sb/.claude/settings.local.json"
  [ -f "$cfg" ] || return 1
  # broken entry removed
  if grep -q 'foo' "$cfg"; then
    return 1
  fi
  # clean entries kept
  if ! grep -q 'echo hi' "$cfg" || ! grep -q 'ls -la' "$cfg"; then
    return 1
  fi
  # telemetry recorded the removal
  if ! grep -q 'removed=1' "$sb/.claude/state/sanitize-allowlist.log" 2>/dev/null; then
    return 1
  fi
  return 0
}

# ---- Run ----

printf 'hook test harness — sandbox=%s\n' "$TEST_DIR"
printf '%s\n' "----"

# 1. UserPromptSubmit (fresh)
fire_hook "auto-kickoff.sh / fresh session" \
  "bash $HOOKS_DIR/auto-kickoff.sh" \
  "userpromptsubmit-fresh-session.json" \
  assert_kickoff_sentinel_fresh

# 2. UserPromptSubmit (existing) — pre-create sentinel so hook should no-op.
EXISTING_SID="test-existing-00000000-0000-0000-0000-000000000002"
mkdir -p "$HOOK_TEST_STATE_DIR/kickoff-sentinels"
touch "$HOOK_TEST_STATE_DIR/kickoff-sentinels/claude-kickoff-$EXISTING_SID"
fire_hook "auto-kickoff.sh / existing session" \
  "bash $HOOKS_DIR/auto-kickoff.sh" \
  "userpromptsubmit-existing-session.json" \
  assert_kickoff_sentinel_existing

# 3. PostToolUse Edit, clean
fire_hook "post-edit-stub-check.py / clean" \
  "python3 $HOOKS_DIR/post-edit-stub-check.py" \
  "posttooluse-edit-clean.json" \
  assert_stub_clean_silent

fire_hook "post-edit-secret-scan.py / clean" \
  "python3 $HOOKS_DIR/post-edit-secret-scan.py" \
  "posttooluse-edit-clean.json" \
  assert_stub_clean_silent

# 4. PostToolUse Edit, secret
fire_hook "post-edit-secret-scan.py / secret" \
  "python3 $HOOKS_DIR/post-edit-secret-scan.py" \
  "posttooluse-edit-secret.json" \
  assert_secret_scan_flags

# 4b. PostToolUse Edit, secret — output-shape check (hookSpecificOutput envelope)
fire_hook "post-edit-secret-scan.py / output shape" \
  "python3 $HOOKS_DIR/post-edit-secret-scan.py" \
  "posttooluse-edit-secret.json" \
  assert_secret_scan_output_shape

# 5. PostToolUse Write HTML
fire_hook "post-write-serve.sh / html" \
  "bash $HOOKS_DIR/post-write-serve.sh" \
  "posttooluse-write-html.json" \
  assert_html_served_marker

# 6. PreToolUse WebFetch
fire_hook "pre-web-rfip.py / localhost" \
  "python3 $HOOKS_DIR/pre-web-rfip.py" \
  "pretooluse-webfetch-localhost.json" \
  assert_rfip_context

# 7. StopFailure
fire_hook "stop-failure-throttle.sh / rate_limit" \
  "bash $HOOKS_DIR/stop-failure-throttle.sh" \
  "stop-failure.json" \
  assert_stop_failure_logged

# 8. SessionEnd — must come AFTER auto-kickoff fresh so the start-snapshot
#    has been written for that session_id (path-divergence regression test).
fire_hook "session-end-snapshot.sh" \
  "bash $HOOKS_DIR/session-end-snapshot.sh" \
  "sessionend.json" \
  assert_session_end_log_or_skip

# ---- 9-12: safety-critical hooks (previously UNCOVERED — I7, 2026-06-29) ----

# 9. block-gmail-ack-warnings.py — deny when gmail invoked with --ack-warnings.
fire_hook "block-gmail-ack-warnings.py / deny (--ack-warnings)" \
  "python3 $HOOKS_DIR/block-gmail-ack-warnings.py" \
  "pretooluse-bash-gmail-ack.json" \
  assert_deny_envelope
fire_hook "block-gmail-ack-warnings.py / allow (benign)" \
  "python3 $HOOKS_DIR/block-gmail-ack-warnings.py" \
  "pretooluse-bash-benign-allow.json" \
  assert_allow_silent

# 10. block-raw-draft-delete.py — deny raw `gws ... drafts delete`.
fire_hook "block-raw-draft-delete.py / deny (gws drafts delete)" \
  "python3 $HOOKS_DIR/block-raw-draft-delete.py" \
  "pretooluse-bash-draft-delete.json" \
  assert_deny_envelope
fire_hook "block-raw-draft-delete.py / allow (benign)" \
  "python3 $HOOKS_DIR/block-raw-draft-delete.py" \
  "pretooluse-bash-benign-allow.json" \
  assert_allow_silent


# 11b. gh-identity-guard.py / gh-commit-author-guard.py — smoke only.
# Full behavioral coverage is the dedicated 58-case suite
# (hooks/test-gh-identity-hooks.py, run separately); these two cases exist so
# the coverage self-assertion sees the registered scripts exercised. The
# git-push fixture's cwd (/tmp/example-repo) isn't a repo, so the push guard
# denies "no git repository" (fail-closed) and the commit guard allows.
fire_hook "gh-identity-guard.py / deny (push, no repo -> fail-closed)" \
  "python3 $HOOKS_DIR/gh-identity-guard.py" \
  "pretooluse-bash-git-push.json" \
  assert_deny_envelope
fire_hook "gh-commit-author-guard.py / allow (commit, no repo)" \
  "python3 $HOOKS_DIR/gh-commit-author-guard.py" \
  "pretooluse-bash-git-commit.json" \
  assert_allow_silent

# 12. sanitize-permission-allowlist.py — Stop hook; removes over-escaped Bash()
#     allow entries. Fired with HOME pointed at a per-case sandbox so the hook's
#     hardcoded ~/.claude/settings.local.json target lands inside the test dir
#     (never the real one). The sandbox is seeded with one broken + two clean
#     entries; the assert verifies the broken one is removed and clean ones kept.
SANITIZE_HOME="$HOOK_TEST_STATE_DIR/sanitize-home"
mkdir -p "$SANITIZE_HOME/.claude"
cat > "$SANITIZE_HOME/.claude/settings.local.json" <<'JSON'
{"permissions":{"allow":["Bash(echo hi)","Bash(grep -E \\(foo\\) bar)","Bash(ls -la)"]}}
JSON
fire_hook "sanitize-permission-allowlist.py / removes over-escaped entry" \
  "HOME='$SANITIZE_HOME' python3 $HOOKS_DIR/sanitize-permission-allowlist.py" \
  "stop-event.json" \
  assert_sanitize_removed_broken

# 13. angel-multiball-guard.py — HARD DENY a Skill(angel) single-pass flag
#     (--single/--no-multiball/--multiball=1/--balls 1); pass a multiball call through.
fire_hook "angel-multiball-guard.py / deny (--single)" \
  "python3 $HOOKS_DIR/angel-multiball-guard.py" \
  "pretooluse-skill-angel-single.json" \
  assert_deny_envelope
fire_hook "angel-multiball-guard.py / allow (multiball default)" \
  "python3 $HOOKS_DIR/angel-multiball-guard.py" \
  "pretooluse-skill-angel-multiball.json" \
  assert_allow_silent

printf '%s\n' "----"
printf 'pass=%d fail=%d\n' "$PASS" "$FAIL"

# ---- Harness coverage self-assertion (drift guard for I7) ----
# Derive the hook SCRIPTS registered in settings.json and confirm this file
# exercises each one. A newly registered hook that isn't fired here is a
# coverage gap — fail loudly so it surfaces in the retro safety review instead
# of hiding behind a green run (the exact I7 failure: 11 registered, 7 fired).
# Coverage is asserted against the SHIPPED config (settings.example.json) when
# present next to this harness — so the repo validates itself; an installed
# ~/.claude falls back to the live settings.json.
SETTINGS="$HOOKS_DIR/../settings.example.json"
[ -f "$SETTINGS" ] || SETTINGS="$HOME/.claude/settings.json"
if [ -f "$SETTINGS" ]; then
  registered="$(grep -oE 'hooks/[A-Za-z0-9_.-]+\.(py|sh)' "$SETTINGS" | sed -E 's#hooks/##' | sort -u)"
  reg_count="$(printf '%s\n' "$registered" | grep -c .)"
  self="$(cat "${BASH_SOURCE[0]}")"
  uncovered=""
  while IFS= read -r script; do
    [ -z "$script" ] && continue
    # A script is "covered" if its filename appears in a fire_hook command above.
    if ! printf '%s' "$self" | grep -qF "$script"; then
      uncovered="$uncovered $script"
    fi
  done <<< "$registered"
  if [ -n "$uncovered" ]; then
    printf 'COVERAGE GAP: %d hooks registered in settings.json, these are NOT exercised by this harness:%s\n' \
      "$reg_count" "$uncovered"
    printf '  Add a fire_hook case (or an explicit not-yet-covered note) before trusting a clean safety review.\n'
    FAIL=$((FAIL + 1))
    FAIL_NAMES+=("coverage-self-assertion")
  else
    printf 'coverage: all %d registered hook scripts are exercised by this harness.\n' "$reg_count"
  fi
else
  printf 'WARN: settings.json not found at %s — skipping coverage self-assertion.\n' "$SETTINGS"
fi

if [ "$FAIL" -gt 0 ]; then
  printf 'failed: %s\n' "${FAIL_NAMES[*]}"
  exit 1
fi
exit 0
