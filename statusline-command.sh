#!/usr/bin/env bash
# statusline-command.sh — Claude Code status line
# Shows: context bar | rate-limit window + cost | model
#
# Core display (context %, rate-limit window, model) works with no extra setup.
# adapt: two OPTIONAL integrations are read here and degrade gracefully when
# absent — (1) a ccusage block cache for the session cost figure, and (2) a
# ~/.phyllis usage-queue state dir for rate-limit persistence + a hook-health
# marker. Neither is required; the statusline just hides those segments.

input=$(cat)

# --- context window ---
used_pct=$(echo "$input" | jq -r '.context_window.used_percentage // empty')

# --- persist rate limit state (optional queue tool) ---
# adapt: ~/.phyllis is an optional usage-accounting queue. If you don't use it,
# this just writes a small JSON file there; harmless and unread without the tool.
PHYLLIS_HOME="${PHYLLIS_HOME:-$HOME/.phyllis}"
PHYLLIS_STATE="$PHYLLIS_HOME/state"
rl_json=$(echo "$input" | jq -c '.rate_limits // empty')
if [ -n "$rl_json" ] && [ "$rl_json" != "null" ]; then
  mkdir -p "$PHYLLIS_STATE" 2>/dev/null || true
  echo "$rl_json" > "$PHYLLIS_STATE/rate-limits.json" 2>/dev/null || true
fi

# --- model ---
model_name=$(echo "$input" | jq -r '.model.display_name // .model.id // "unknown"')

# --- progress bar (20 chars wide) ---
if [ -n "$used_pct" ]; then
  filled=$(awk -v p="$used_pct" 'BEGIN { printf "%d", int(p * 20 / 100 + 0.5) }')
  empty=$((20 - filled))
  bar=$(printf '%0.s#' $(seq 1 $filled 2>/dev/null) 2>/dev/null || true)
  pad=$(printf '%0.s.' $(seq 1 $empty 2>/dev/null) 2>/dev/null || true)
  bar_display="[${bar}${pad}] ${used_pct}%"
else
  bar_display="[--------------------] --%"
fi

# --- cost (OPTIONAL: from a ccusage block cache) ---
# adapt: this reads a cache file written by ccusage (https://github.com/ryoppippi/ccusage).
# The statusline never invokes ccusage on the hot path — it only reads the cache,
# which you'd refresh out-of-band (e.g. a */5min cron). The one exception is a
# cold-start bootstrap below. If ccusage isn't installed, no cost segment shows.
cache_file="/tmp/ccusage-block-cache"
cache_lock="/tmp/ccusage-block-cache.lock"
cost_display=""

if [ -f "$cache_file" ]; then
  cost=$(cat "$cache_file" | jq -r '.blocks[0].costUSD // empty')
  if [ -n "$cost" ]; then
    cost_display=$(printf '$%.0f' "$cost")
  fi
elif command -v ccusage >/dev/null 2>&1; then
  # No cache yet and ccusage is available — fire one bootstrap refresh in the
  # background, locked. Skipped entirely if ccusage isn't installed.
  (
    flock -n 9 || exit 0
    ccusage blocks --active --json --offline 2>/dev/null > "$cache_file.tmp" && mv "$cache_file.tmp" "$cache_file"
  ) 9>"$cache_lock" &
fi

# --- rate limit window (from API via statusline input) ---
window_display=""
resets_at=$(echo "$input" | jq -r '.rate_limits.five_hour.resets_at // empty')
five_pct=$(echo "$input" | jq -r '.rate_limits.five_hour.used_percentage // empty')

# adapt: OPTIONAL — log rate limit history to your own analytics. Only runs if
# the script exists; safe to leave out.
RATE_LOG_SCRIPT="${RATE_LOG_SCRIPT:-$HOME/.claude/scripts/log-rate-limits.sh}"
seven_resets_at=$(echo "$input" | jq -r '.rate_limits.seven_day.resets_at // empty')
seven_pct=$(echo "$input" | jq -r '.rate_limits.seven_day.used_percentage // empty')
if [ -n "$resets_at" ] && [ -f "$RATE_LOG_SCRIPT" ]; then
  (bash "$RATE_LOG_SCRIPT" "$resets_at" "$five_pct" "$seven_resets_at" "$seven_pct") &
fi

if [ -n "$resets_at" ] && [ -n "$five_pct" ]; then
  now=$(date +%s)
  remaining_sec=$((resets_at - now))
  if [ "$remaining_sec" -gt 0 ]; then
    remaining_h=$((remaining_sec / 3600))
    remaining_m=$(( (remaining_sec % 3600) / 60 ))
    window_display="${five_pct}% | ${remaining_h}h${remaining_m}m left"
  else
    window_display="${five_pct}%"
  fi
elif [ -f "$PHYLLIS_STATE/rate-limits.json" ]; then
  # fallback to persisted rate limits if not in statusline input
  five_hr=$(jq -r '.five_hour.used_percentage // empty' "$PHYLLIS_STATE/rate-limits.json" 2>/dev/null)
  resets_at_fb=$(jq -r '.five_hour.resets_at // empty' "$PHYLLIS_STATE/rate-limits.json" 2>/dev/null)
  if [ -n "$five_hr" ]; then
    if [ -n "$resets_at_fb" ]; then
      now=$(date +%s)
      remaining_sec=$((resets_at_fb - now))
      if [ "$remaining_sec" -gt 0 ]; then
        remaining_h=$((remaining_sec / 3600))
        remaining_m=$(( (remaining_sec % 3600) / 60 ))
        window_display="${five_hr}% | ${remaining_h}h${remaining_m}m left"
      else
        window_display="${five_hr}%"
      fi
    else
      window_display="W:${five_hr}%"
    fi
  fi
fi

# --- hook health marker (OPTIONAL: usage-queue calibration) ---
# adapt: surfaces a visible warning when the optional usage-accounting hooks
# stop writing calibration entries. Trigger: hook-errors.log mtime newer than
# calibration-log.jsonl mtime. Inert if you don't use ~/.phyllis.
hook_marker=""
err_log="$PHYLLIS_STATE/hook-errors.log"
cal_log="$PHYLLIS_HOME/calibration-log.jsonl"
if [ -f "$err_log" ] && [ -f "$cal_log" ]; then
  err_mtime=$(stat -c %Y "$err_log" 2>/dev/null || echo 0)
  cal_mtime=$(stat -c %Y "$cal_log" 2>/dev/null || echo 0)
  if [ "$err_mtime" -gt "$cal_mtime" ]; then
    last_err=$(tail -1 "$err_log" 2>/dev/null | sed 's/^\[[^]]*\] //; s/^session-end: //' | tr -cd '[:print:]' | cut -c1-40)
    hook_marker=" ⚠ HOOK: ${last_err}"
  fi
fi

# --- assemble ---
parts="$bar_display"
[ -n "$cost_display" ] && parts="$parts  $cost_display"
[ -n "$window_display" ] && parts="$parts  $window_display"
parts="$parts  $model_name"
[ -n "$hook_marker" ] && parts="$parts$hook_marker"
printf '%s' "$parts"
