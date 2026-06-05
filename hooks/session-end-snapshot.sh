#!/usr/bin/env bash
# OPTIONAL hook: per-session usage accounting. Needs ccusage + a ~/.phyllis
# state dir; no-ops cleanly when either is absent.
# Computes per-session delta from start snapshot, appends to a calibration log.
#
# Failure mode: on any error path, append a structured line to hook-errors.log.
# The statusline checks that log against the calibration log mtime to surface
# a visible warning when entries stop flowing — see statusline-command.sh.

# Source shared utils. STATE_DIR here MUST match auto-kickoff.sh's STATE_DIR
# or per-session deltas silently drop.
HOOK_LIB="$(dirname "${BASH_SOURCE[0]}")/lib/hook-utils.sh"
if [ -f "$HOOK_LIB" ]; then
  # shellcheck source=lib/hook-utils.sh
  source "$HOOK_LIB"
fi

# In test mode, redirect PHYLLIS_HOME under the test state dir so the hook
# writes to a sandbox instead of ~/.phyllis. The dir layout matches prod.
if [ -n "${HOOK_TEST_STATE_DIR:-}" ]; then
  PHYLLIS_HOME="${HOOK_TEST_STATE_DIR}/phyllis-home"
  mkdir -p "$PHYLLIS_HOME" 2>/dev/null
fi
PHYLLIS_HOME="${PHYLLIS_HOME:-$HOME/.phyllis}"
LOG_PATH="$PHYLLIS_HOME/calibration-log.jsonl"
if type hook_phyllis_state_dir >/dev/null 2>&1; then
  STATE_DIR="$(hook_phyllis_state_dir)"
else
  STATE_DIR="$PHYLLIS_HOME/state"
fi
ERR_LOG="$STATE_DIR/hook-errors.log"

log_err() {
  # Use shared hook_log if available; falls back to the legacy inline writer
  # so this script still works with an old (or missing) hook-utils.sh.
  local reason="$1"
  if type hook_log >/dev/null 2>&1; then
    hook_log ERROR "$reason"
    return 0
  fi
  local ts
  ts=$(date -u +%Y-%m-%dT%H:%M:%S.000Z 2>/dev/null || echo "unknown")
  if [ -d "$STATE_DIR" ]; then
    printf '[%s] session-end-snapshot.sh: ERROR: %s\n' "$ts" "$reason" \
      >> "$ERR_LOG" 2>/dev/null
  fi
}

# The usage queue dir must exist for this hook to do anything meaningful.
# This is the one error path that's not really an error: the optional queue
# tool isn't installed. We exit silently without logging.
if [ ! -d "$PHYLLIS_HOME" ]; then
  exit 0
fi

# Read hook input for session_id
input=$(cat)
SESSION_ID=$(echo "$input" | jq -r '.session_id // empty' 2>/dev/null)
if [ -z "$SESSION_ID" ]; then
  log_err "no session_id in hook input"
  exit 0
fi
# Guard: SESSION_ID is interpolated into file paths below; reject anything outside [A-Za-z0-9_-].
case "$SESSION_ID" in *[!A-Za-z0-9_-]*) log_err "rejected non-safe session_id"; exit 0 ;; esac

# Get current block state (refresh cache first)
if ! ccusage blocks --active --json --offline 2>/dev/null > /tmp/ccusage-block-cache.tmp; then
  log_err "ccusage blocks failed for session=$SESSION_ID"
  rm -f /tmp/ccusage-block-cache.tmp
  exit 0
fi
mv /tmp/ccusage-block-cache.tmp /tmp/ccusage-block-cache

CACHE="/tmp/ccusage-block-cache"
if [ ! -s "$CACHE" ]; then
  log_err "ccusage cache missing/empty for session=$SESSION_ID"
  exit 0
fi

now_tokens=$(jq -r '.blocks[0].totalTokens // 0' "$CACHE")
now_cost=$(jq -r '.blocks[0].costUSD // 0' "$CACHE")
now_start=$(jq -r '.blocks[0].startTime // empty' "$CACHE")
now_end=$(jq -r '.blocks[0].endTime // empty' "$CACHE")
now_models=$(jq -c '.blocks[0].models // ["unknown"]' "$CACHE")
now_remaining=$(jq -r '.blocks[0].projection.remainingMinutes // empty' "$CACHE")
now_input=$(jq -r '.blocks[0].tokenCounts.inputTokens // 0' "$CACHE")
now_output=$(jq -r '.blocks[0].tokenCounts.outputTokens // 0' "$CACHE")
now_cache_create=$(jq -r '.blocks[0].tokenCounts.cacheCreationInputTokens // 0' "$CACHE")
now_cache_read=$(jq -r '.blocks[0].tokenCounts.cacheReadInputTokens // 0' "$CACHE")

# Try to compute per-session delta from session-start snapshot.
START_FILE="$STATE_DIR/session-start-${SESSION_ID}"
session_tokens=""
session_cost=""
session_input=""
session_output=""
session_cache_create=""
session_cache_read=""
rl_before_5h=""
rl_before_7d=""

if [ -n "$SESSION_ID" ] && [ -f "$START_FILE" ]; then
  start_block_id=$(jq -r '.blocks[0].startTime // empty' "$START_FILE")
  # Only diff if same block (session didn't span a window boundary)
  if [ "$start_block_id" = "$now_start" ]; then
    start_tokens=$(jq -r '.blocks[0].totalTokens // 0' "$START_FILE")
    start_cost=$(jq -r '.blocks[0].costUSD // 0' "$START_FILE")
    start_input=$(jq -r '.blocks[0].tokenCounts.inputTokens // 0' "$START_FILE")
    start_output=$(jq -r '.blocks[0].tokenCounts.outputTokens // 0' "$START_FILE")
    start_cache_create=$(jq -r '.blocks[0].tokenCounts.cacheCreationInputTokens // 0' "$START_FILE")
    start_cache_read=$(jq -r '.blocks[0].tokenCounts.cacheReadInputTokens // 0' "$START_FILE")

    session_tokens=$(awk "BEGIN {printf \"%.0f\", $now_tokens - $start_tokens}")
    session_cost=$(awk "BEGIN {printf \"%.2f\", $now_cost - $start_cost}")
    session_input=$(awk "BEGIN {printf \"%.0f\", $now_input - $start_input}")
    session_output=$(awk "BEGIN {printf \"%.0f\", $now_output - $start_output}")
    session_cache_create=$(awk "BEGIN {printf \"%.0f\", $now_cache_create - $start_cache_create}")
    session_cache_read=$(awk "BEGIN {printf \"%.0f\", $now_cache_read - $start_cache_read}")
  fi
  # Pull rate_limits at session-start (added by auto-kickoff.sh's wrapper).
  # Older start files don't have this — they'll just yield empty.
  rl_before_5h=$(jq -r '.rate_limits.five_hour.used_percentage // empty' "$START_FILE" 2>/dev/null)
  rl_before_7d=$(jq -r '.rate_limits.seven_day.used_percentage // empty' "$START_FILE" 2>/dev/null)
  rm -f "$START_FILE"
fi

# Read end-state rate limits
rl_cache="$STATE_DIR/rate-limits.json"
five_hr=$(jq -r '.five_hour.used_percentage // empty' "$rl_cache" 2>/dev/null)
seven_day=$(jq -r '.seven_day.used_percentage // empty' "$rl_cache" 2>/dev/null)

now=$(date -u +%Y-%m-%dT%H:%M:%S.000Z)

# Build entry. `rate_limits` retained as alias for `rate_limits_after` for
# backward compatibility with existing readers; new analysis uses the explicit
# before/after pair.
if ! jq -nc \
  --arg user_id "${USER:-unknown}" \
  --arg session_id "${SESSION_ID:-unknown}" \
  --arg window_start "$now_start" \
  --arg window_end "$now_end" \
  --arg observed_at "$now" \
  --argjson block_tokens "${now_tokens}" \
  --argjson block_cost "${now_cost}" \
  --argjson remaining "${now_remaining:-null}" \
  --argjson models "$now_models" \
  --argjson block_input "${now_input}" \
  --argjson block_output "${now_output}" \
  --argjson block_cache_create "${now_cache_create}" \
  --argjson block_cache_read "${now_cache_read}" \
  --argjson session_tokens "${session_tokens:-null}" \
  --argjson session_cost "${session_cost:-null}" \
  --argjson session_input "${session_input:-null}" \
  --argjson session_output "${session_output:-null}" \
  --argjson session_cache_create "${session_cache_create:-null}" \
  --argjson session_cache_read "${session_cache_read:-null}" \
  --argjson rl_before_5h "${rl_before_5h:-null}" \
  --argjson rl_before_7d "${rl_before_7d:-null}" \
  --argjson five_hr_pct "${five_hr:-null}" \
  --argjson seven_day_pct "${seven_day:-null}" \
  '{
    user_id: $user_id,
    session_id: $session_id,
    window_start: $window_start,
    window_end: $window_end,
    observed_at: $observed_at,
    block_tokens: $block_tokens,
    block_cost: $block_cost,
    session_tokens: $session_tokens,
    session_cost: $session_cost,
    remaining_min: $remaining,
    throttled: null,
    model_mix: $models,
    source: "session-end-hook",
    block_breakdown: {
      input: $block_input,
      output: $block_output,
      cache_creation: $block_cache_create,
      cache_read: $block_cache_read
    },
    session_breakdown: (if $session_tokens != null then {
      input: $session_input,
      output: $session_output,
      cache_creation: $session_cache_create,
      cache_read: $session_cache_read
    } else null end),
    rate_limits_before: (if $rl_before_5h != null then {
      five_hour_pct: $rl_before_5h,
      seven_day_pct: $rl_before_7d
    } else null end),
    rate_limits_after: (if $five_hr_pct != null then {
      five_hour_pct: $five_hr_pct,
      seven_day_pct: $seven_day_pct
    } else null end),
    rate_limits: (if $five_hr_pct != null then {
      five_hour_pct: $five_hr_pct,
      seven_day_pct: $seven_day_pct
    } else null end)
  }' >> "$LOG_PATH"; then
  log_err "jq failed to build entry for session=$SESSION_ID"
  exit 0
fi

exit 0
