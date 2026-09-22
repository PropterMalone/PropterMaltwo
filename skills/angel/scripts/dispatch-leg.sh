#!/usr/bin/env bash
# pattern: imperative shell
# Headless codex-backend leg adapter. All durable run bookkeeping is delegated
# to record-dispatch.sh, the ADR-12 single-writer chokepoint.
#
# Usage:
#   dispatch-leg.sh --run-dir RUN_DIR --phase persona|reconciler|verifier \
#     --name SHORT_NAME --model MODEL_ID [--pass I] [--findings] [--note TEXT] \
#     < prompt
set -euo pipefail

SCRIPT_DIR="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"

RUN_DIR=""
PHASE=""
NAME=""
MODEL=""
PASS_I=""
FINDINGS=false
NOTE=""

usage() {
  echo 'usage: dispatch-leg.sh --run-dir <RUN_DIR> --phase <persona|reconciler|verifier> --name <short-name> --model <model-id> [--pass I] [--findings] [--note "..."] < prompt-on-stdin' >&2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-dir)  [[ $# -ge 2 ]] || { usage; exit 1; }; RUN_DIR="$2"; shift 2 ;;
    --phase)    [[ $# -ge 2 ]] || { usage; exit 1; }; PHASE="$2"; shift 2 ;;
    --name)     [[ $# -ge 2 ]] || { usage; exit 1; }; NAME="$2"; shift 2 ;;
    --model)    [[ $# -ge 2 ]] || { usage; exit 1; }; MODEL="$2"; shift 2 ;;
    --pass)     [[ $# -ge 2 ]] || { usage; exit 1; }; PASS_I="$2"; shift 2 ;;
    --findings) FINDINGS=true; shift ;;
    --note)     [[ $# -ge 2 ]] || { usage; exit 1; }; NOTE="$2"; shift 2 ;;
    -h|--help)  usage; exit 0 ;;
    *) echo "error: unknown argument '$1'" >&2; usage; exit 1 ;;
  esac
done

[[ -d "$RUN_DIR" ]] || { echo "error: run dir not found: $RUN_DIR" >&2; exit 1; }
case "$PHASE" in persona|reconciler|verifier) ;; *)
  echo "error: phase must be persona|reconciler|verifier (got '$PHASE')" >&2; exit 1 ;;
esac
[[ "$NAME" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "error: name must match [A-Za-z0-9_-]+ (got '$NAME')" >&2; exit 1; }
[[ -n "$MODEL" ]] || { echo "error: --model is required" >&2; exit 1; }
if [[ -n "$PASS_I" ]]; then
  [[ "$PASS_I" =~ ^[0-9]+$ && "$PASS_I" -ge 1 ]] \
    || { echo "error: --pass I must be a positive integer (got '$PASS_I')" >&2; exit 1; }
fi
if $FINDINGS && [[ -n "$PASS_I" && "$PASS_I" != "1" ]]; then
  echo "error: --findings only composes with --pass 1 (pass-1's block is the findings/ record)" >&2
  exit 1
fi

mkdir -p "$RUN_DIR/tmp"
PROMPT_FILE="$(mktemp "$RUN_DIR/tmp/dispatch-${NAME}-prompt.XXXXXX")"
OUTPUT_FILE="$(mktemp "$RUN_DIR/tmp/dispatch-${NAME}-output.XXXXXX")"
BLOCK_FILE="$(mktemp "$RUN_DIR/tmp/dispatch-${NAME}-block.XXXXXX")"
SESSION_MARKER="$(mktemp "$RUN_DIR/tmp/dispatch-${NAME}-sessions.XXXXXX")"
trap 'rm -f "$PROMPT_FILE" "$OUTPUT_FILE" "$BLOCK_FILE" "$SESSION_MARKER"' EXIT

# Read the caller's stdin to EOF before starting codex so the headless process
# never inherits a caller fd that may remain open. Codex must then receive the
# saved prompt on stdin with `-` as its prompt argument: persona-size prompts
# passed as argv can complete a turn without flushing stdout or exiting.
cat > "$PROMPT_FILE"

touch "$SESSION_MARKER"
START_NS="$(date +%s%N)"
CODEX_RC=0
DISPATCH_TIMEOUT_S="${DISPATCH_TIMEOUT_S:-2100}"
# Reject disabling/garbage values: GNU timeout treats 0 as "no timeout", which
# silently re-opens the no-exit strand this guard exists to close. Fractional
# seconds are valid (the test shim uses 0.1); zero in any spelling is not.
if [[ ! "$DISPATCH_TIMEOUT_S" =~ ^[0-9]*\.?[0-9]+$ ]] || [[ "$DISPATCH_TIMEOUT_S" =~ ^0*\.?0*$ ]]; then
  echo "error: DISPATCH_TIMEOUT_S must be a positive duration in seconds (got '$DISPATCH_TIMEOUT_S')" >&2
  exit 1
fi
# Pinned binary with env override (CODEX_BIN) for test shims. Never bare-PATH:
# ~/.local/bin is absent from non-login shells (cron, hooks), and a stale
# /usr/bin/codex has already burned one plan built against the wrong version.
CODEX_BIN="${CODEX_BIN:-$HOME/.local/bin/codex}"
[[ -x "$CODEX_BIN" ]] || { echo "error: codex binary not found/executable: $CODEX_BIN (set CODEX_BIN)" >&2; exit 1; }
timeout --kill-after=30 "$DISPATCH_TIMEOUT_S" \
  "$CODEX_BIN" exec -c 'sandbox_mode="danger-full-access"' -m "$MODEL" - \
  < "$PROMPT_FILE" >"$OUTPUT_FILE" 2>&1 || CODEX_RC=$?
END_NS="$(date +%s%N)"
DURATION_MS="$(( (END_NS - START_NS) / 1000000 ))"

# Codex emits the final response after a line containing only "codex", followed
# near the end by "tokens used" and its comma-formatted total. Test shims and
# some CLI versions omit the role marker, so fall back to everything preceding
# the meter marker; record-dispatch performs the authoritative structure check.
python3 - "$OUTPUT_FILE" "$BLOCK_FILE" <<'PY'
import re
import sys

source, target = sys.argv[1:]
text = open(source, encoding="utf-8", errors="replace").read()
lines = text.splitlines()
meter = [i for i, line in enumerate(lines) if re.fullmatch(r"\s*tokens used\s*(?::\s*[\d,]+)?\s*", line, re.I)]
if not meter:
    open(target, "w").close()
    raise SystemExit(0)
end = meter[-1]
roles = [i for i, line in enumerate(lines[:end]) if line.strip().lower() == "codex"]
start = roles[-1] + 1 if roles else 0
block = "\n".join(lines[start:end]).strip()
open(target, "w", encoding="utf-8").write(block + ("\n" if block else ""))
PY

TOKENS="$(python3 - "$OUTPUT_FILE" <<'PY'
import re
import sys

lines = open(sys.argv[1], encoding="utf-8", errors="replace").read().splitlines()
found = None
for i, line in enumerate(lines):
    inline = re.fullmatch(r"\s*tokens used\s*:\s*([\d,]+)\s*", line, re.I)
    if inline:
        found = inline.group(1)
        continue
    if re.fullmatch(r"\s*tokens used\s*", line, re.I):
        for candidate in lines[i + 1:]:
            candidate = candidate.strip()
            if not candidate:
                continue
            if re.fullmatch(r"[\d,]+", candidate):
                found = candidate
            break
print(found.replace(",", "") if found else "")
PY
)"

# Prefer the model claimed in exec output. If absent, inspect only rollout files
# created by this dispatch and matching the current working directory.
RAN_MODEL="$(python3 - "$OUTPUT_FILE" <<'PY'
import json
import re
import sys

model = ""
for line in open(sys.argv[1], encoding="utf-8", errors="replace"):
    m = re.match(r"^\s*model\s*:\s*(\S+)\s*$", line, re.I)
    if m:
        model = m.group(1)
    else:
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        candidate = obj.get("model") if isinstance(obj, dict) else None
        if isinstance(candidate, str) and candidate:
            model = candidate
print(model)
PY
)"
if [[ -z "$RAN_MODEL" && -d "${CODEX_HOME:-$HOME/.codex}/sessions" ]]; then
  while IFS= read -r rollout; do
    [[ -n "$rollout" ]] || continue
    meta_cwd="$(jq -r 'select(.type == "session_meta") | .payload.cwd // empty' "$rollout" 2>/dev/null | head -1)"
    [[ "$meta_cwd" == "$PWD" ]] || continue
    RAN_MODEL="$(jq -r 'select(.type == "turn_context") | .payload.model // empty' "$rollout" 2>/dev/null | tail -1)"
    [[ -n "$RAN_MODEL" ]] && break
  done < <(find "${CODEX_HOME:-$HOME/.codex}/sessions" -type f -name '*.jsonl' -newer "$SESSION_MARKER" \
    -printf '%T@ %p\n' 2>/dev/null | sort -nr | cut -d' ' -f2-)
fi

if [[ -z "$RAN_MODEL" ]]; then
  MODEL_NOTE="requested=$MODEL|ran=unverified"
elif [[ "$RAN_MODEL" == "$MODEL" ]]; then
  MODEL_NOTE="requested=$MODEL|ran=$RAN_MODEL"
else
  MODEL_NOTE="requested=$MODEL|ran=$RAN_MODEL MODEL_MISMATCH"
fi
if [[ -n "$NOTE" ]]; then
  NOTE="$NOTE; $MODEL_NOTE"
else
  NOTE="$MODEL_NOTE"
fi

# Classify the exit status ONCE, into wording the durable record can carry. A
# bare number is not actionable to a later reader of usage.jsonl: 124 is GNU
# timeout's deadline code and 137 its kill-after escalation, and neither reads
# as "timed out" to a human or to a grep. The numbers stay in the text too.
#
# The non-numeric guard runs FIRST and is not dead code. `$?` is always numeric
# today, but `[[ $x -eq 0 ]]` evaluates its operands ARITHMETICALLY, so garbage
# fails silently rather than loudly, and never as the 125 it would be mistaken
# for: an empty CODEX_RC satisfies `-eq 0`, so the leg records a clean SUCCESS
# and a killed turn's block is written as a real pass; a bare word aborts the
# whole script under `set -u` ("abc: unbound variable") after codex already
# burned its tokens and before any durable record exists. Both are one edit
# away — assigning CODEX_RC from a command substitution is all it takes.
rc_label=""
if [[ ! "$CODEX_RC" =~ ^[0-9]+$ ]]; then
  rc_label="codex return code unavailable (got '$CODEX_RC') — not a codex exit status"
  CODEX_RC=256  # outside the 0-255 exit space, so no comparison below matches
elif [[ "$CODEX_RC" -eq 124 ]]; then
  rc_label="codex timed out after ${DISPATCH_TIMEOUT_S}s (exit 124)"
elif [[ "$CODEX_RC" -eq 137 ]]; then
  rc_label="codex died on SIGKILL (exit 137) — most likely timed out after ${DISPATCH_TIMEOUT_S}s and ignored SIGTERM, so the guard's kill-after escalated; an external kill (OOM) is indistinguishable"
elif [[ "$CODEX_RC" -eq 125 ]]; then
  rc_label="exit 125 — GNU timeout reserves 125 for the wrapper's own failure, so codex may never have run; a genuine codex status of 125 is indistinguishable"
elif [[ "$CODEX_RC" -ne 0 ]]; then
  rc_label="codex exit $CODEX_RC"
fi

failure_reason="$rc_label"
[[ -n "$TOKENS" ]] || failure_reason="${failure_reason:+$failure_reason; }tokens-used parse failed"
[[ -s "$BLOCK_FILE" ]] || failure_reason="${failure_reason:+$failure_reason; }final response parse failed"

# Avoid record-dispatch's known append-before-pass-parse ordering on a malformed
# response: preflight the same parser, then let record-dispatch check again while
# doing the only durable writes.
if [[ -z "$failure_reason" && ( -n "$PASS_I" || "$FINDINGS" == true ) ]]; then
  parse_status="$(python3 "$SCRIPT_DIR/parse-findings.py" "$BLOCK_FILE" 2>/dev/null || true)"
  [[ "$parse_status" != "no-structure" ]] \
    || failure_reason="final response has no recognizable finding structure"
fi

PRESERVE_FAILED=""

record_failure() {
  local why="$1" failed_pass="${PASS_I:-1}" failed_tokens="${TOKENS:-null}"
  [[ -z "$PRESERVE_FAILED" ]] || why="$why; $PRESERVE_FAILED"
  "$SCRIPT_DIR/record-dispatch.sh" --backend codex --failed --pass "$failed_pass" \
    "$RUN_DIR" "$PHASE" "$NAME" "$MODEL" "$failed_tokens" null "$DURATION_MS" \
    "$NOTE; FAILED: $why" >/dev/null
}

# Never let a bookkeeping refusal destroy the model's work — and never let a
# failure to SAVE that work destroy the record of the loss too. This runs as a
# plain command under `set -e`, so an unguarded `cp` (full disk, read-only run
# dir) aborted the script before record_failure ever ran: the leg lost the
# output AND the durable failure line, which is the exact gap record_failure
# exists to fill. Failing to preserve is worth a warning, never a silent exit.
preserve_rejected_output() {
  local rejected_output="$RUN_DIR/tmp/rejected-${NAME}-$(date +%s%N).out"
  if cp -- "$OUTPUT_FILE" "$rejected_output"; then
    echo "captured codex output preserved at: $rejected_output" >&2
  else
    PRESERVE_FAILED="captured codex output could NOT be preserved to $rejected_output — it is lost"
    echo "warning: $PRESERVE_FAILED" >&2
  fi
  return 0
}

if [[ -n "$failure_reason" ]]; then
  preserve_rejected_output
  record_failure "$failure_reason"
  echo "error: codex leg failed: $failure_reason" >&2
  # 124/137 both mean the process was killed mid-flight, so the turn may exist
  # in the rollout even though nothing usable reached stdout.
  if [[ "$CODEX_RC" -eq 124 || "$CODEX_RC" -eq 137 ]]; then
    echo "       rollout recovery may be available under ~/.codex/sessions" >&2
  fi
  exit 1
fi

record_flags=(--backend codex)
[[ -n "$PASS_I" ]] && record_flags+=(--pass "$PASS_I")
$FINDINGS && record_flags+=(--findings)
if ! "$SCRIPT_DIR/record-dispatch.sh" "${record_flags[@]}" \
  "$RUN_DIR" "$PHASE" "$NAME" "$MODEL" "$TOKENS" null "$DURATION_MS" "$NOTE" \
  < "$BLOCK_FILE"; then
  preserve_rejected_output
  record_failure "record-dispatch rejected final response"
  echo "error: record-dispatch rejected codex leg output" >&2
  exit 1
fi
