#!/usr/bin/env bash
# OPTIONAL hook: rate-limit telemetry. Needs a ~/.phyllis state dir; no-ops
# cleanly when it's absent.
# StopFailure hook: detect rate limit events and annotate a calibration log.
# Fires when a turn ends due to an API error — we only care about rate_limit.

# Source shared utils so HOOK_TEST_STATE_DIR redirects work and hook_log
# is available. Falls through to legacy paths if the lib is missing.
HOOK_LIB="$(dirname "${BASH_SOURCE[0]}")/lib/hook-utils.sh"
if [ -f "$HOOK_LIB" ]; then
  # shellcheck source=lib/hook-utils.sh
  source "$HOOK_LIB"
fi

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

# Read hook input
input=$(cat)
error_type=$(echo "$input" | jq -r '.error // empty')

# Only act on rate limit events
if [ "$error_type" != "rate_limit" ]; then
  exit 0
fi

# The usage queue dir must exist for telemetry to land somewhere. If the
# optional queue tool isn't installed, no-op silently.
if [ ! -d "$PHYLLIS_HOME" ]; then
  exit 0
fi

# Capture current block state from ccusage cache (fast, no npx)
cache_file="/tmp/ccusage-block-cache"
block_json=""
if [ -f "$cache_file" ]; then
  block_json=$(cat "$cache_file")
fi

window_start=$(echo "$block_json" | jq -r '.blocks[0].startTime // empty')
tokens=$(echo "$block_json" | jq -r '.blocks[0].totalTokens // 0')
cost=$(echo "$block_json" | jq -r '.blocks[0].costUSD // 0')
models=$(echo "$block_json" | jq -c '.blocks[0].models // ["unknown"]')

# Read rate limit state from statusline cache if available
rl_cache="$STATE_DIR/rate-limits.json"
window_pct=""
if [ -f "$rl_cache" ]; then
  window_pct=$(jq -r '.five_hour.used_percentage // empty' "$rl_cache")
fi

now=$(date -u +%Y-%m-%dT%H:%M:%S.000Z)

# Build calibration entry (compact: one JSON object per line for the .jsonl log)
entry=$(jq -nc \
  --arg user_id "${USER:-unknown}" \
  --arg window_start "${window_start:-$now}" \
  --arg observed_at "$now" \
  --argjson tokens "${tokens:-0}" \
  --argjson cost "${cost:-0}" \
  --argjson models "${models:-[\"unknown\"]}" \
  --arg window_pct "${window_pct:-unknown}" \
  '{
    user_id: $user_id,
    window_start: $window_start,
    window_end: "",
    observed_at: $observed_at,
    tokens_consumed: $tokens,
    cost_equiv: $cost,
    remaining_min: 0,
    throttled: true,
    peak_hour: false,
    promo_active: false,
    model_mix: $models,
    source: "manual",
    notes: ("Rate limit hit detected by StopFailure hook. Window pct at throttle: " + $window_pct + "%")
  }')

echo "$entry" >> "$LOG_PATH"

# Also output context back to the conversation
jq -n --arg msg "Rate limit detected — throttle data point captured to calibration log." \
  '{"additionalContext": $msg}'
