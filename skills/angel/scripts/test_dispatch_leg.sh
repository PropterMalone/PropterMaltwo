#!/usr/bin/env bash
# pattern: imperative shell
# Guard tests for dispatch-leg.sh, the codex-backend leg adapter (ADR-18). Each
# case here pins a guard whose absence already cost a real run something: the
# durable failure record must NAME a timeout (a bare 124 teaches a later reader
# nothing), a non-numeric return code must not read as success or as a genuine
# exit 125, a failed preservation `cp` must not swallow the failure record, and
# rc-124-WITH-complete-output — the historical "finished the turn, never exited"
# shape the timeout guard exists for — must fail the leg while keeping both the
# token count and the model's block.
#
# Hermetic: codex is always a shim, CODEX_HOME is redirected at a temp dir, and
# nothing here makes a network call or spends codex quota.
#
# Run: scripts/test_dispatch_leg.sh
#      DISPATCH_LEG_BIN=/path/to/another/dispatch-leg.sh scripts/test_dispatch_leg.sh
# The env override runs this same suite against a different copy of the script —
# that is how each guard below was proved to FAIL against the pre-fix version.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP="$(mktemp -d)"
export ANGEL_RUNS_ROOT="$TMP/runs"
export ANGEL_USAGE_LOG="$TMP/usage.log"
# Never let the real rollout store answer a model question during a test.
export CODEX_HOME="$TMP/codex-home"
mkdir -p "$ANGEL_RUNS_ROOT"
PASS=0; FAIL=0
trap 'rm -rf "$TMP"' EXIT

ok()   { PASS=$((PASS+1)); printf 'ok   - %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf 'FAIL - %s\n     %s\n' "$1" "${2:-}"; }
has()  { case "$2" in *"$1"*) ok "$3";; *) bad "$3" "missing '$1' in: $2";; esac; }
hasnt(){ case "$2" in *"$1"*) bad "$3" "unexpected '$1' in: $2";; *) ok "$3";; esac; }
rc_is(){ [ "$1" = "$2" ] && ok "$3" || bad "$3" "rc=$1 expected $2"; }

LEG_SRC="${DISPATCH_LEG_BIN:-$DIR/dispatch-leg.sh}"
[ -f "$LEG_SRC" ] || { echo "error: no dispatch-leg.sh at $LEG_SRC" >&2; exit 1; }

# Stage the script under test beside copies of the siblings it shells out to
# (it resolves them from its own path). Everything runs out of $TMP, so a
# mutant — or a pre-fix copy passed via DISPATCH_LEG_BIN — never needs a file
# written into the repo.
# mktemp, not a counter: this runs inside `$( )`, so a counter would increment in
# a subshell and every staged copy would collide on one directory — which is how
# an early draft of this file silently ran the wrong script.
stage_leg() { # [sed-expr] -> path to a runnable dispatch-leg.sh
  local d
  d="$(mktemp -d "$TMP/legXXXXXX")"
  cp "$DIR/record-dispatch.sh" "$DIR/parse-findings.py" "$d/"
  if [ $# -ge 1 ]; then sed "$1" "$LEG_SRC" > "$d/dispatch-leg.sh"; else cp "$LEG_SRC" "$d/dispatch-leg.sh"; fi
  chmod +x "$d/dispatch-leg.sh"
  printf '%s\n' "$d/dispatch-leg.sh"
}
LEG="$(stage_leg)"

SHIM_DIR="$TMP/codex-shim"; mkdir -p "$SHIM_DIR"
SHIM="$SHIM_DIR/codex"

mk_run() { local rd="$ANGEL_RUNS_ROOT/$1"; mkdir -p "$rd"; printf '%s\n' "$rd"; }
note_of() { # $1=run dir -> note field of the last usage.jsonl line ("" if none)
  [ -s "$1/usage.jsonl" ] || return 0
  python3 -c 'import json,sys
lines=[json.loads(l) for l in open(sys.argv[1]) if l.strip()]
print(lines[-1].get("note","") if lines else "")' "$1/usage.jsonl"
}
tokens_of() { # $1=run dir -> total_tokens of the last usage.jsonl line
  [ -s "$1/usage.jsonl" ] || return 0
  python3 -c 'import json,sys
lines=[json.loads(l) for l in open(sys.argv[1]) if l.strip()]
print(lines[-1].get("total_tokens") if lines else "")' "$1/usage.jsonl"
}
preserved_of() { # $1=run dir -> path of the preserved rejected output ("" if none)
  find "$1/tmp" -maxdepth 1 -type f -name 'rejected-adv-*.out' -print -quit 2>/dev/null || true
}

# A complete, well-formed codex turn: role marker, one parseable finding, meter.
write_complete_output_shim() { # $1=trailing shell line(s) after the output
  cat > "$SHIM" <<SH
#!/usr/bin/env bash
cat >/dev/null
/bin/cat <<'OUT'
OpenAI Codex stub
model: gpt-5.6-sol
codex
## [Adversarial] Review
#### Important
- **complete before the kill** \`[trivial]\` — \`stub.py:3\` — full block, process never exited
tokens used
9,876
OUT
$1
SH
  chmod +x "$SHIM"
}

echo "== dispatch-leg: harness sanity (shimmed happy path) =="
write_complete_output_shim 'exit 0'
RD="$(mk_run r_happy)"
rc=0; out="$(printf 'review this\n' | CODEX_BIN="$SHIM" "$LEG" \
  --run-dir "$RD" --phase persona --name adv --model gpt-5.6-sol --pass 1 2>&1)" || rc=$?
rc_is $rc 0 "happy path exits 0 through the staged script"
[ -f "$RD/passes/adv-p1.md" ] && ok "happy path writes the pass file" || bad "happy path writes the pass file" "$out"
[ "$(tokens_of "$RD")" = "9876" ] && ok "happy path records the token meter" || bad "happy path records the token meter" "got: $(tokens_of "$RD")"

echo
echo "== item 1: the durable failure record must say the leg TIMED OUT =="
# Partial output, then a process that never exits — plain rc 124.
cat > "$SHIM" <<'SH'
#!/usr/bin/env bash
cat >/dev/null
printf '%s\n' 'partial output before the deadline'
exec sleep 5
SH
chmod +x "$SHIM"
RD="$(mk_run r_timeout_note)"
rc=0; out="$(printf 'review this\n' | CODEX_BIN="$SHIM" DISPATCH_TIMEOUT_S=0.3 "$LEG" \
  --run-dir "$RD" --phase persona --name adv --model gpt-5.6-sol --pass 1 2>&1)" || rc=$?
rc_is $rc 1 "rc-124 leg exits nonzero"
note="$(note_of "$RD")"
has "FAILED:" "$note" "rc-124 leg writes a durable failure record"
has "timed out" "$note" "rc-124 failure RECORD says 'timed out' (not just the stderr)"
has "0.3s" "$note" "rc-124 failure record names the deadline it blew"
has "124" "$note" "rc-124 failure record keeps the numeric code for machine readers"
hasnt "codex exit 124" "$note" "rc-124 record no longer reports a bare 'codex exit 124'"
has "timed out after 0.3s" "$out" "rc-124 stderr keeps its distinct timeout wording"
has "~/.codex/sessions" "$out" "rc-124 stderr keeps the rollout-recovery hint"

echo
echo "== item 1b: SIGKILL (137), the kill-after escalation shape =="
cat > "$SHIM" <<'SH'
#!/usr/bin/env bash
cat >/dev/null
printf '%s\n' 'partial output before the kill'
kill -9 $$
SH
chmod +x "$SHIM"
RD="$(mk_run r_sigkill)"
rc=0; out="$(printf 'review this\n' | CODEX_BIN="$SHIM" DISPATCH_TIMEOUT_S=5 "$LEG" \
  --run-dir "$RD" --phase persona --name adv --model gpt-5.6-sol --pass 1 2>&1)" || rc=$?
rc_is $rc 1 "rc-137 leg exits nonzero"
note="$(note_of "$RD")"
has "137" "$note" "rc-137 failure record keeps the numeric code"
has "SIGKILL" "$note" "rc-137 failure record names the signal"
has "timed out" "$note" "rc-137 failure record surfaces the timeout hypothesis (kill-after escalation)"
hasnt "codex exit 137" "$note" "rc-137 record no longer reports a bare 'codex exit 137'"

echo
echo "== item 2: exit 125 is the timeout WRAPPER's failure code, not codex's =="
cat > "$SHIM" <<'SH'
#!/usr/bin/env bash
cat >/dev/null
exit 125
SH
chmod +x "$SHIM"
RD="$(mk_run r_rc125)"
rc=0; out="$(printf 'review this\n' | CODEX_BIN="$SHIM" "$LEG" \
  --run-dir "$RD" --phase persona --name adv --model gpt-5.6-sol --pass 1 2>&1)" || rc=$?
rc_is $rc 1 "rc-125 leg exits nonzero"
note="$(note_of "$RD")"
has "125" "$note" "rc-125 failure record keeps the numeric code"
has "wrapper" "$note" "rc-125 record flags that the timeout wrapper may have failed, not codex"
hasnt "codex exit 125" "$note" "rc-125 record no longer asserts codex exited 125"

echo
echo "== item 2b: a non-numeric CODEX_RC must not read as success, or as a 125 =="
# `$?` is always numeric, so the garbage path is reached by mutating the
# initializer — the guard exists for the next edit that assigns CODEX_RC from a
# command substitution. `[[ "" -eq 0 ]]` is TRUE and `[[ abc -eq 0 ]]` is a fatal
# `set -u` error, so both shapes are invisible failures without the guard.
write_complete_output_shim 'exit 0'

LEG_EMPTY="$(stage_leg 's/^CODEX_RC=0$/CODEX_RC=""/')"
grep -q '^CODEX_RC=""$' "$LEG_EMPTY" && ok "empty-rc mutant applied (initializer still matches)" \
  || bad "empty-rc mutant applied (initializer still matches)" "sed did not match CODEX_RC=0"
RD="$(mk_run r_rc_empty)"
rc=0; out="$(printf 'review this\n' | CODEX_BIN="$SHIM" "$LEG_EMPTY" \
  --run-dir "$RD" --phase persona --name adv --model gpt-5.6-sol --pass 1 2>&1)" || rc=$?
rc_is $rc 1 "empty CODEX_RC fails the leg (does not silently pass -eq 0)"
note="$(note_of "$RD")"
has "return code unavailable" "$note" "empty CODEX_RC is recorded as an unavailable return code"
hasnt "125" "$note" "empty CODEX_RC is not misattributed to exit 125"
grep -q 'failed' "$RD/passes/adv-p1.md" 2>/dev/null \
  && ok "empty CODEX_RC writes a failure stub, not a real pass" \
  || bad "empty CODEX_RC writes a failure stub, not a real pass" "pass file: $(cat "$RD/passes/adv-p1.md" 2>/dev/null)"

LEG_WORD="$(stage_leg 's/^CODEX_RC=0$/CODEX_RC=abc/')"
grep -q '^CODEX_RC=abc$' "$LEG_WORD" && ok "bare-word-rc mutant applied" \
  || bad "bare-word-rc mutant applied" "sed did not match CODEX_RC=0"
RD="$(mk_run r_rc_word)"
rc=0; out="$(printf 'review this\n' | CODEX_BIN="$SHIM" "$LEG_WORD" \
  --run-dir "$RD" --phase persona --name adv --model gpt-5.6-sol --pass 1 2>&1)" || rc=$?
rc_is $rc 1 "bare-word CODEX_RC fails the leg"
hasnt "unbound variable" "$out" "bare-word CODEX_RC does not abort the script under set -u"
note="$(note_of "$RD")"
has "return code unavailable" "$note" "bare-word CODEX_RC still produces a durable failure record"
has "abc" "$note" "bare-word CODEX_RC record quotes the garbage value"
hasnt "125" "$note" "bare-word CODEX_RC is not misattributed to exit 125"

echo
echo "== item 3: a failed preservation cp must not swallow the failure record =="
CPFAIL="$TMP/cpfail"; mkdir -p "$CPFAIL"
cat > "$CPFAIL/cp" <<'SH'
#!/usr/bin/env bash
echo "cp: cannot create regular file: No space left on device (test shim)" >&2
exit 1
SH
chmod +x "$CPFAIL/cp"
cat > "$SHIM" <<'SH'
#!/usr/bin/env bash
cat >/dev/null
printf '%s\n' 'garbage output with no final block or meter'
exit 0
SH
chmod +x "$SHIM"
RD="$(mk_run r_cp_fails)"
rc=0; out="$(printf 'review this\n' | PATH="$CPFAIL:$PATH" CODEX_BIN="$SHIM" "$LEG" \
  --run-dir "$RD" --phase persona --name adv --model gpt-5.6-sol --pass 1 2>&1)" || rc=$?
rc_is $rc 1 "leg still exits nonzero when the preservation cp fails"
note="$(note_of "$RD")"
has "FAILED:" "$note" "failure is STILL recorded when the preservation cp fails"
has "tokens-used parse failed" "$note" "the original failure reason survives the cp failure"
has "could NOT be preserved" "$note" "the record also states the output was lost"
has "could NOT be preserved" "$out" "stderr warns that the captured output is lost"
[ -f "$RD/passes/adv-p1.md" ] && ok "failure stub pass file is still written after a failed cp" \
  || bad "failure stub pass file is still written after a failed cp"
# The same guard protects the second call site (record-dispatch rejection).
cat > "$SHIM" <<'SH'
#!/usr/bin/env bash
cat >/dev/null
/bin/cat <<'OUT'
OpenAI Codex stub
model: gpt-5.6-sol
codex
#### Important
- **rejected by record-dispatch** `[trivial]` — `stub.py:2` — multiball needs --pass
tokens used
234
OUT
SH
chmod +x "$SHIM"
RD="$(mk_run r_cp_fails_reject)"; printf '2\n' > "$RD/MULTIBALL"
rc=0; out="$(printf 'review this\n' | PATH="$CPFAIL:$PATH" CODEX_BIN="$SHIM" "$LEG" \
  --run-dir "$RD" --phase persona --name adv --model gpt-5.6-sol 2>&1)" || rc=$?
rc_is $rc 1 "record-dispatch-rejection path exits nonzero when the cp also fails"
note="$(note_of "$RD")"
has "record-dispatch rejected" "$note" "rejection path still records its failure when the cp fails"

echo
echo "== item 4: rc-124 WITH complete output (finished the turn, never exited) =="
write_complete_output_shim 'exec sleep 5'
RD="$(mk_run r_timeout_complete)"
rc=0; out="$(printf 'review this\n' | CODEX_BIN="$SHIM" DISPATCH_TIMEOUT_S=0.5 "$LEG" \
  --run-dir "$RD" --phase persona --name adv --model gpt-5.6-sol --pass 1 --findings 2>&1)" || rc=$?
rc_is $rc 1 "complete-output timeout still FAILS the leg (killed process is not a clean turn)"
note="$(note_of "$RD")"
has "timed out" "$note" "complete-output timeout is recorded as a timeout"
hasnt "tokens-used parse failed" "$note" "complete-output timeout does not claim the meter failed to parse"
hasnt "final response parse failed" "$note" "complete-output timeout does not claim the block failed to parse"
[ "$(tokens_of "$RD")" = "9876" ] && ok "complete-output timeout still records the tokens codex burned" \
  || bad "complete-output timeout still records the tokens codex burned" "got: $(tokens_of "$RD")"
has '"backend":"codex"' "$(tail -1 "$RD/usage.jsonl")" "complete-output timeout keeps the codex backend on the failure line"
grep -qE 'angel-pass persona=adv pass=1 model=gpt-5.6-sol( backend=codex)? failed' "$RD/passes/adv-p1.md" 2>/dev/null \
  && ok "complete-output timeout records a failure stub, not the killed turn's block" \
  || bad "complete-output timeout records a failure stub, not the killed turn's block" "$(cat "$RD/passes/adv-p1.md" 2>/dev/null)"
[ ! -e "$RD/findings/adv.md" ] && ok "complete-output timeout writes no findings/ record" \
  || bad "complete-output timeout writes no findings/ record"
kept="$(preserved_of "$RD")"
[ -n "$kept" ] && grep -q 'complete before the kill' "$kept" \
  && ok "complete-output timeout preserves the killed turn's work for recovery" \
  || bad "complete-output timeout preserves the killed turn's work for recovery" "preserved: ${kept:-<none>}"

echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
