#!/usr/bin/env bash
# pattern: imperative shell
# Smoke tests pinning the angel script contracts. Exercises every script against
# fixtures and asserts behavior — so the usage.json schema and the finding-id
# contract (shared by append-usage-log.sh, mine-runs.py, record-disposition.py,
# check-run-complete.py) can't silently drift. Run: scripts/test_scripts.sh
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP="$(mktemp -d)"
export ANGEL_RUNS_ROOT="$TMP/runs"
export ANGEL_USAGE_LOG="$TMP/usage.log"
mkdir -p "$ANGEL_RUNS_ROOT"
PASS=0; FAIL=0
trap 'rm -rf "$TMP"' EXIT

ok()   { PASS=$((PASS+1)); printf 'ok   - %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf 'FAIL - %s\n     %s\n' "$1" "${2:-}"; }
has()  { case "$2" in *"$1"*) ok "$3";; *) bad "$3" "missing '$1' in: $2";; esac; }
hasnt(){ case "$2" in *"$1"*) bad "$3" "unexpected '$1' in: $2";; *) ok "$3";; esac; }
rc_is(){ [ "$1" = "$2" ] && ok "$3" || bad "$3" "rc=$1 expected $2"; }

mk_usage() { # $1=rundir $2=total_tokens(null|int) ; writes a full-schema usage.json
  local rd="$1" tok="$2"
  mkdir -p "$rd/findings"
  cat > "$rd/usage.json" <<JSON
{"run_dir":"$rd","project":"demo","mode":"full","reader_enabled":true,
 "started_at":"2026-05-31T12:00:00Z","ended_at":"2026-05-31T12:05:00Z",
 "totals":{"total_tokens":$tok,"wall_seconds":300,
   "reader":{"total_tokens":40000,"duration_ms":22000,"tool_uses":9},
   "personas":[{"name":"rtfm","model":"claude-sonnet-4-6","total_tokens":50000,"reader_pack":true},
               {"name":"adv","model":"claude-sonnet-4-6","total_tokens":60000,"reader_pack":true}]},
 "unmeasured":[],"verdict":"CHANGES REQUIRED","findings":{"critical":1,"important":2,"minor":0,"noted":1}}
JSON
}
mk_snapshot() { # $1=rundir : snapshot with ids + evidence + a shared finding
  cat > "$1/findings-snapshot.json" <<'JSON'
{"version":1,"project":"demo","date":"2026-05-31","mode":"full","verdict":"CHANGES REQUIRED",
 "personas_run":["rtfm","adv"],
 "findings":[
  {"id":"f1","severity":"critical","title":"Spec | violated `here`","personas":["rtfm"],"evidence":"cited-spec"},
  {"id":"f2","severity":"important","title":"Path traversal","personas":["adv"],"evidence":"code-site"},
  {"id":"f3","severity":"important","title":"Both caught this","personas":["rtfm","adv"],"evidence":"code-site"},
  {"id":"f4","severity":"minor","title":"Vague","personas":["rtfm"],"evidence":"inference"}
 ]}
JSON
}

echo "== validate-personas =="
out="$("$DIR/validate-personas.py" 2>&1)"; rc_is $? 0 "validate-personas exits 0 (registry clean)"
has "clean" "$out" "validate-personas reports clean"

echo "== append-usage-log.sh =="
RD="$ANGEL_RUNS_ROOT/r_full"; mk_usage "$RD" 110000
line="$("$DIR/append-usage-log.sh" "$RD")"
has "total:110000" "$line" "normal run emits total:<int>"
has "run:$RD" "$line" "line carries run: pointer"
has "reader_total:40000" "$line" "reader_total present when reader block exists"
RDN="$ANGEL_RUNS_ROOT/r_null"; mk_usage "$RDN" null
lineN="$("$DIR/append-usage-log.sh" "$RDN")"
has "total:null" "$lineN" "null tokens emit total:null (not total:0)"
hasnt "total:0 " "$lineN" "null tokens do NOT masquerade as total:0"
RDC="$ANGEL_RUNS_ROOT/r_cal"; mk_usage "$RDC" 5000
lineC="$("$DIR/append-usage-log.sh" "$RDC" baseline)"
has "cal:baseline" "$lineC" "calibration tag becomes cal:<tag>"
RDM="$ANGEL_RUNS_ROOT/r_missing"; mkdir -p "$RDM/findings"
lineM="$("$DIR/append-usage-log.sh" "$RDM" 2>/dev/null)"
has "usage.json-missing" "$lineM" "missing usage.json -> fallback line"
has "run:$RDM" "$lineM" "fallback line still carries run: pointer"
RDX="$ANGEL_RUNS_ROOT/r_bad"; mkdir -p "$RDX/findings"; echo '{bad json' > "$RDX/usage.json"
lineX="$("$DIR/append-usage-log.sh" "$RDX" 2>/dev/null)"
has "usage.json-malformed" "$lineX" "malformed usage.json -> fallback line"

echo "== record-disposition.py =="
"$DIR/record-disposition.py" "$RD" f1 accepted >/dev/null; rc_is $? 0 "record accepted ok"
"$DIR/record-disposition.py" "$RD" f4 rejected-wrong not a real bug at all >/dev/null
note="$(python3 -c "import json;print(json.load(open('$RD/dispositions.json'))['f4']['note'])")"
[ "$note" = "not a real bug at all" ] && ok "note joins unquoted words" || bad "note joins unquoted words" "got: $note"
"$DIR/record-disposition.py" "$RD" f9 bogus-disp 2>/dev/null; rc_is $? 1 "invalid disposition rejected"
"$DIR/record-disposition.py" /etc f1 accepted 2>/dev/null; rc_is $? 1 "write outside runs-root rejected"

echo "== mine-runs.py (evidence + precision + overlap) =="
mk_snapshot "$RD"; echo "stub" > "$RD/findings/rtfm.md"
mout="$("$DIR/mine-runs.py" --runs-dir "$ANGEL_RUNS_ROOT" --since 2026-05-31)"
has "cited%" "$mout" "value table has cited% column"
has "fp% (n)" "$mout" "value table has fp% column"
has "Persona overlap" "$mout" "overlap section emitted"
has "adv + rtfm" "$mout" "overlap lists the shared-Important+ pair"
mjson="$("$DIR/mine-runs.py" --runs-dir "$ANGEL_RUNS_ROOT" --since 2026-05-31 --json)"
python3 - "$mjson" <<'PY'
import json,sys
d=json.loads(sys.argv[1])
rt=d["personas"]["rtfm"]
assert rt["disposed"]==2, rt           # f1 + f4 dispositioned
assert rt["false_positives"]==1, rt    # f4 rejected-wrong
assert rt["cited"]>=1, rt              # f1 cited-spec
assert any(o["pair"]==["adv","rtfm"] for o in d["portfolio"]["overlap_important_plus"]), d["portfolio"]["overlap_important_plus"]
print("json-asserts-ok")
PY
rc_is $? 0 "mine-runs --json: disposed/fp/cited/overlap correct"

echo "== check-run-complete.py =="
"$DIR/append-usage-log.sh" "$RD" >/dev/null   # ensures a run: line in $ANGEL_USAGE_LOG
"$DIR/check-run-complete.py" "$RD" >/dev/null 2>&1; rc_is $? 0 "complete run passes"
"$DIR/check-run-complete.py" "$RDN" >/dev/null 2>&1; rc_is $? 1 "incomplete run fails (no findings/snapshot)"
"$DIR/check-run-complete.py" --all >/dev/null 2>&1; rc_is $? 1 "--all exits nonzero when any run incomplete"

echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
