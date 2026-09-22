#!/usr/bin/env bash
# ctx-nudge.sh — UserPromptSubmit hook. Surfaces the standing per-turn cost of
# an already-large context, so a long session stops being invisibly expensive.
#
# WHY per-turn and not cumulative: each assistant turn's cache_read_input_tokens
# IS the size of the cached prefix re-read that turn. It is the *marginal* cost
# of keeping the context alive — every future turn pays it again until a
# /clear. Reading one value beats summing a history, and it stays O(1) against
# a transcript that can run to several MB. A hook that parsed the whole file
# on every prompt would itself become the burn it is trying to report.
#
# WHY it never says "clear now": the hook cannot tell dead weight from the
# thing you are three steps into debugging. Clearing mid-arc converts cheap
# cache reads (a fraction of the input rate) into full-price re-reads —
# strictly worse. So the copy stays conditional and the decision stays human.
#
# Fires only on an UPWARD tier crossing, and stays quiet for QUIET_TURNS after
# a reset. A hook that nags every prompt gets tuned out inside a day, and a
# tuned-out hook is worse than no hook.
#
# Never blocks and never fails a turn: every path exits 0.

set -uo pipefail

# Honor the harness sandbox (lib/hook-utils.sh contract) so test-hooks.sh can
# exercise this hook without writing production state. Inlined rather than
# sourced: this hook runs on EVERY prompt and must stay dependency-free.
if [ -n "${HOOK_TEST_STATE_DIR:-}" ]; then
  STATE_DIR="${HOOK_TEST_STATE_DIR}/claude-state"
else
  STATE_DIR="$HOME/.claude/state"
fi
mkdir -p "$STATE_DIR" 2>/dev/null || true

# Thresholds in cache-read tokens per turn, and the $/Mtok rate used to turn
# a token count into a dollar estimate.
#
# adapt: CTX_NUDGE_PRICE_PER_MTOK is MODEL-SPECIFIC — cache-read pricing (and
# the input:cache-read ratio) differs by model and by vendor. The default
# below (~$0.50/Mtok) assumes a frontier-tier model where cache reads bill at
# roughly 10% of a ~$5/Mtok input rate; check your provider's current pricing
# and override via the env var rather than trusting this default. The token
# thresholds (250k/500k/900k) are a reasonable starting ladder for a ~1M-token
# context window — halve them for a smaller window.
T1="${CTX_NUDGE_T1:-250000}"
T2="${CTX_NUDGE_T2:-500000}"
T3="${CTX_NUDGE_T3:-900000}"
QUIET_TURNS="${CTX_NUDGE_QUIET_TURNS:-10}"
PRICE_PER_MTOK="${CTX_NUDGE_PRICE_PER_MTOK:-0.50}"

INPUT=$(cat 2>/dev/null || echo '{}')

jqf() { printf '%s' "$INPUT" | jq -r "$1 // empty" 2>/dev/null || true; }

SESSION_ID=$(jqf '.session_id')
TRANSCRIPT=$(jqf '.transcript_path')
CWD=$(jqf '.cwd')

# transcript_path is the documented field, but don't depend on it: reconstruct
# from session_id + cwd (the projects dir slugifies cwd with / -> -) if absent.
if [ -z "$TRANSCRIPT" ] || [ ! -f "$TRANSCRIPT" ]; then
  if [ -n "$SESSION_ID" ]; then
    SLUG=$(printf '%s' "${CWD:-$PWD}" | sed 's#/#-#g')
    CAND="$HOME/.claude/projects/${SLUG}/${SESSION_ID}.jsonl"
    [ -f "$CAND" ] && TRANSCRIPT="$CAND"
  fi
fi
[ -z "$TRANSCRIPT" ] || [ ! -f "$TRANSCRIPT" ] && exit 0

# Newest cache_read_input_tokens. Tail bytes, not lines: one line can be huge.
CR=$(tail -c 400000 "$TRANSCRIPT" 2>/dev/null \
      | grep -o '"cache_read_input_tokens":[0-9]*' \
      | tail -1 | cut -d: -f2)
case "$CR" in ''|*[!0-9]*) exit 0 ;; esac

if   [ "$CR" -ge "$T3" ]; then TIER=3
elif [ "$CR" -ge "$T2" ]; then TIER=2
elif [ "$CR" -ge "$T1" ]; then TIER=1
else TIER=0
fi

SFILE="$STATE_DIR/ctx-nudge-${SESSION_ID:-unknown}.json"
PREV_TIER=0; PREV_CR=0; TURN=0
if [ -f "$SFILE" ]; then
  PREV_TIER=$(jq -r '.tier // 0' "$SFILE" 2>/dev/null || echo 0)
  PREV_CR=$(jq -r '.cr // 0'   "$SFILE" 2>/dev/null || echo 0)
  TURN=$(jq -r '.turn // 0'    "$SFILE" 2>/dev/null || echo 0)
fi
TURN=$((TURN + 1))

# A large drop in per-turn cache reads means the context was reset. Re-arm the
# ladder and go quiet, so the rebuild climb doesn't immediately re-nag.
QUIET_UNTIL=$(jq -r '.quiet_until // 0' "$SFILE" 2>/dev/null || echo 0)
if [ "$PREV_CR" -gt 0 ] && [ "$CR" -lt $((PREV_CR / 2)) ] && [ "$PREV_CR" -gt "$T1" ]; then
  PREV_TIER=0
  QUIET_UNTIL=$((TURN + QUIET_TURNS))
fi

printf '{"tier":%s,"cr":%s,"turn":%s,"quiet_until":%s}\n' \
  "$TIER" "$CR" "$TURN" "$QUIET_UNTIL" > "$SFILE" 2>/dev/null || true

[ "$TIER" -le "$PREV_TIER" ] && exit 0          # only upward crossings
[ "$TURN" -le "$QUIET_UNTIL" ] && exit 0        # post-reset grace
[ "$TIER" -eq 0 ] && exit 0

K=$((CR / 1000))
PER_TURN=$(awk -v c="$CR" -v p="$PRICE_PER_MTOK" 'BEGIN{printf "%.2f", c/1000000*p}')
NEXT20=$(awk -v c="$CR" -v p="$PRICE_PER_MTOK" 'BEGIN{printf "%.2f", c/1000000*p*20}')

case "$TIER" in
  1) echo "⚠ Context ${K}k/turn (~\$${PER_TURN} each, ~\$${NEXT20} per 20 turns). /clear if you're between arcs." ;;
  2) echo "⚠⚠ Context ${K}k/turn (~\$${PER_TURN} each, ~\$${NEXT20} per 20 turns). Every turn re-reads this. /clear at the next arc boundary." ;;
  3) echo "⚠⚠⚠ Context ${K}k/turn (~\$${PER_TURN} each, ~\$${NEXT20} per 20 turns). This is the dominant cost of the session now — /clear unless the whole context is load-bearing." ;;
esac
exit 0
