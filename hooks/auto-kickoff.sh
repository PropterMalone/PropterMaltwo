#!/bin/bash
# Auto-kickoff: fires on first UserPromptSubmit per session.
# Creates a sentinel in /tmp keyed by session_id; no-ops on subsequent messages.
# adapt: also saves ccusage block state + rate_limits for per-session delta
# tracking. Both the ccusage cache and the ~/.phyllis state dir are OPTIONAL —
# the snapshot block below no-ops cleanly when they're absent.

# Source shared utils for hook_phyllis_state_dir() and hook_log().
# Falls back to hardcoded paths if the lib is missing (defense in depth).
HOOK_LIB="$(dirname "${BASH_SOURCE[0]}")/lib/hook-utils.sh"
if [ -f "$HOOK_LIB" ]; then
  # shellcheck source=lib/hook-utils.sh
  source "$HOOK_LIB"
fi

SESSION_ID=$(jq -r '.session_id // empty' 2>/dev/null)
if [ -z "$SESSION_ID" ]; then
  exit 0
fi
# Guard: SESSION_ID is interpolated into file paths below; reject anything outside [A-Za-z0-9_-].
case "$SESSION_ID" in *[!A-Za-z0-9_-]*) exit 0 ;; esac

# Sentinel lives in /tmp (cleared on reboot, OK for per-session de-dup).
# In test mode it lives under HOOK_TEST_STATE_DIR so concurrent harness runs
# don't collide and so cleanup is automatic.
if [ -n "${HOOK_TEST_STATE_DIR:-}" ]; then
  SENTINEL_DIR="${HOOK_TEST_STATE_DIR}/kickoff-sentinels"
  mkdir -p "$SENTINEL_DIR" 2>/dev/null || true
  SENTINEL="${SENTINEL_DIR}/claude-kickoff-${SESSION_ID}"
else
  SENTINEL="/tmp/claude-kickoff-${SESSION_ID}"
fi

if [ -f "$SENTINEL" ]; then
  exit 0
fi

touch "$SENTINEL"

# adapt: optional per-session usage delta tracking.
# Save a start snapshot wrapping ccusage block state + current rate_limits +
# capture timestamp. session-end-snapshot.sh reads this file to compute deltas.
#
# IMPORTANT: STATE_DIR here MUST resolve to the same path that
# session-end-snapshot.sh uses to read SESSION_START_FILE. Path divergence
# between these two hooks silently drops per-session deltas. Both go through
# hook_phyllis_state_dir() to keep them in lockstep.
#
# If you don't have ccusage installed, the cache file won't exist and this
# whole block no-ops.
CACHE="/tmp/ccusage-block-cache"
if type hook_phyllis_state_dir >/dev/null 2>&1; then
  STATE_DIR="$(hook_phyllis_state_dir)"
else
  STATE_DIR="${HOME}/.phyllis/state"
fi
RL_FILE="${STATE_DIR}/rate-limits.json"
if [ -f "$CACHE" ]; then
  mkdir -p "$STATE_DIR"
  blocks_json=$(jq -c '.blocks // []' "$CACHE" 2>/dev/null || echo '[]')
  if [ -f "$RL_FILE" ]; then
    rl_json=$(cat "$RL_FILE")
  else
    rl_json="null"
  fi
  captured_at=$(date -u +%Y-%m-%dT%H:%M:%S.000Z)
  printf '{"blocks":%s,"rate_limits":%s,"captured_at":"%s"}\n' \
    "$blocks_json" "$rl_json" "$captured_at" \
    > "${STATE_DIR}/session-start-${SESSION_ID}"
fi

# adapt: this injects an instruction to run a /kickoff skill at session start.
# If you don't have a /kickoff skill, drop this heredoc (or replace with your
# own session-start context).
cat <<'EOF'
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "AUTO-KICKOFF: This is the first message of this session and /kickoff has not run yet. Before responding to the user's message, run the /kickoff skill first. Exception: if the user's message is itself '/kickoff', just proceed with it directly — don't double-invoke."
  }
}
EOF
