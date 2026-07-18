#!/usr/bin/env bash
# statusline-command.sh — Claude Code status line
# Shows: context bar | block time remaining + cost | model
# adapt: core display (context %, rate-limit window, model) needs no setup.
# Optional integrations (ccusage cost cache, ~/.phyllis rate-limit persistence,
# hook-health marker, rate-log script) all degrade gracefully when absent.

input=$(cat)

# --- context window ---
# used_percentage comes pre-computed from CC, but its denominator (context_window_size)
# is wrongly 200000 on 1M-context sessions (anthropics/claude-code#39702, #61734).
# Absolute tokens are always trustworthy, so show them alongside; once tokens exceed
# the reported size, the session is provably 1M — recompute against 1e6 and tag it.
used_pct=$(echo "$input" | jq -r '.context_window.used_percentage // empty')
used_tok=$(echo "$input" | jq -r '.context_window.total_input_tokens // empty')
win_size=$(echo "$input" | jq -r '.context_window.context_window_size // empty')
tok_display=""
win_tag=""
if [ -n "$used_tok" ]; then
  tok_display=$(awk -v t="$used_tok" 'BEGIN { printf "%dk", int(t/1000) }')
  if [ -n "$win_size" ] && [ "$used_tok" -gt "$win_size" ]; then
    used_pct=$(awk -v t="$used_tok" 'BEGIN { printf "%d", t/10000 }')  # % of 1M
    win_tag="/1m"
  fi
fi
# (b) configured-model override: settings.json names a [1m] model but payload says 200k
if [ -z "$win_tag" ] && [ "$win_size" = "200000" ] && [ -n "$used_tok" ]; then
  case "$(jq -r '.model // empty' "$HOME/.claude/settings.json" 2>/dev/null)" in
    *"[1m]"*)
      used_pct=$(awk -v t="$used_tok" 'BEGIN { printf "%d", t/10000 }')
      win_tag="/1m"
      ;;
  esac
fi

# --- persist rate limit state (optional queue tool) ---
# adapt: ~/.phyllis is an optional usage-accounting queue. If you don't use it,
# this just writes a small JSON file there; harmless and unread without the tool.
PHYLLIS_HOME="${PHYLLIS_HOME:-$HOME/.phyllis}"
PHYLLIS_STATE="$PHYLLIS_HOME/state"
rl_json=$(echo "$input" | jq -c '.rate_limits // empty')
if [ -n "$rl_json" ] && [ "$rl_json" != "null" ]; then
  mkdir -p "$PHYLLIS_STATE"
  echo "$rl_json" > "$PHYLLIS_STATE/rate-limits.json"
fi

# --- model (+ fallback detection: live model vs configured model in settings.json) ---
model_name=$(echo "$input" | jq -r '.model.display_name // .model.id // "unknown"')
model_id=$(echo "$input" | jq -r '.model.id // empty')
configured_model=$(jq -r '.model // empty' "$HOME/.claude/settings.json" 2>/dev/null)
fallback_marker=""
if [ -n "$model_id" ] && [ -n "$configured_model" ]; then
  configured_base="${configured_model%%\[*}"
  # substring match: alias "fable" resolves to id "claude-fable-5", prefix match false-alarms
  case "$model_id" in
    *"$configured_base"*) ;;
    *) fallback_marker=" ⚠ FALLBACK" ;;
  esac
fi

# --- progress bar (20 chars wide) ---
# Percentage (and the bar it drives) renders ONLY when the denominator is trusted
# (win_tag set: 1M proven or [1m] configured). Otherwise the payload's 200k-based
# percentage is likely wrong on this machine's habitual 1M sessions — show raw
# tokens only, which are always accurate.
if [ -n "$win_tag" ] && [ -n "$used_pct" ]; then
  # printf '%0.s#' with an empty arg list still emits one char — build via awk instead
  bar=$(awk -v p="$used_pct" 'BEGIN { f = int(p * 20 / 100 + 0.5); if (f > 20) f = 20; if (f < 0) f = 0;
    for (i = 0; i < f; i++) printf "#"; for (i = f; i < 20; i++) printf "." }')
  bar_display="[${bar}] ${used_pct}%${win_tag} ${tok_display}"
elif [ -n "$tok_display" ]; then
  bar_display="ctx ${tok_display}"
else
  bar_display="ctx --"
fi

# --- cost (ccusage cache, refreshed by ~/.claude/scripts/refresh-ccusage-cache.sh cron */5min) ---
# The statusline never invokes ccusage itself — only reads the cache.
# Cold-start bootstrap (e.g. post-reboot before first cron tick) is the one exception.
cache_file="/tmp/ccusage-block-cache"
cache_lock="/tmp/ccusage-block-cache.lock"
cost_display=""

if [ -f "$cache_file" ]; then
  cost=$(cat "$cache_file" | jq -r '.blocks[0].costUSD // empty')
  if [ -n "$cost" ]; then
    cost_display=$(printf '$%.0f' "$cost")
  fi
else
  # No cache yet — fire one bootstrap refresh in the background, locked.
  (
    flock -n 9 || exit 0
    ccusage blocks --active --json --offline 2>/dev/null > "$cache_file.tmp" && mv "$cache_file.tmp" "$cache_file"
  ) 9>"$cache_lock" &
fi

# --- rate limit window (from API via statusline input) ---
window_display=""
resets_at=$(echo "$input" | jq -r '.rate_limits.five_hour.resets_at // empty')
five_pct=$(echo "$input" | jq -r '.rate_limits.five_hour.used_percentage // empty')

# log rate limit history (deduped, background)
seven_resets_at=$(echo "$input" | jq -r '.rate_limits.seven_day.resets_at // empty')
seven_pct=$(echo "$input" | jq -r '.rate_limits.seven_day.used_percentage // empty')
if [ -n "$resets_at" ]; then
  (bash "$HOME/.claude/scripts/log-rate-limits.sh" "$resets_at" "$five_pct" "$seven_resets_at" "$seven_pct") &
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

# --- Phyllis hook health marker ---
# Surface a visible warning when calibration data has stopped flowing.
# Trigger: hook-errors.log mtime newer than calibration-log.jsonl mtime.
# (If errors are older than the last successful entry, things have recovered.)
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
parts="$parts  $model_name$fallback_marker"
[ -n "$hook_marker" ] && parts="$parts$hook_marker"
printf '%s' "$parts"
