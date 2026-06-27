#!/usr/bin/env bash
# pattern: imperative shell
# Smoke tests pinning the angel script contracts. Exercises every script against
# fixtures and asserts behavior — so the usage.json schema and the finding-id
# contract (shared by append-usage-log.sh, mine-runs.py, record-disposition.py,
# check-run-complete.py) can't silently drift. Run: scripts/test_scripts.sh
set -euo pipefail

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
rc=0; out="$("$DIR/validate-personas.py" 2>&1)" || rc=$?; rc_is $rc 0 "validate-personas exits 0 (registry clean)"
has "clean" "$out" "validate-personas reports clean"
# Synthetic-drift fixtures: prove the detector actually fires (not just clean-on-live).
vp_fixture() { # $1=dir $2=SKILL rows $3=unattended rows (data rows only)
  rm -rf "$1"; mkdir -p "$1/personas"
  printf '# fixture\n\n| Short | Full | Model |\n|---|---|---|\n%s\n' "$2" > "$1/SKILL.md"
  printf '# fixture\n\n| Short | Persona file | Model |\n|---|---|---|\n%s\n' "$3" > "$1/unattended.md"
}
mk_persona() { # $1=path ; writes a contract-conformant persona file (DESIGN.md frontmatter contract)
  cat > "$1" <<'PERSONA'
---
name: adversarial
default: yes
modes: [diff, full]
experimental: false
requires:
  any_of: [any]
context:
  digest: yes
  project_claude_md: yes
  full_bundle: no
  lane: |
    fixture lane
---
fixture body
PERSONA
}
VP="$TMP/vp"
vp_fixture "$VP" '| adv | Adversarial | Sonnet 4.6 |' '| adv | `adversarial.md` | `claude-sonnet-4-6` |'
mk_persona "$VP/personas/adversarial.md"
rc=0; vout="$("$DIR/validate-personas.py" --skill-dir "$VP" 2>&1)" || rc=$?
rc_is $rc 0 "drift fixture baseline is clean"
vp_fixture "$VP" $'| adv | Adversarial | Sonnet 4.6 |\n| ghost | Ghost | Sonnet 4.6 |' \
  $'| adv | `adversarial.md` | `claude-sonnet-4-6` |\n| ghost | `ghost.md` | `claude-sonnet-4-6` |'
rc=0; vout="$("$DIR/validate-personas.py" --skill-dir "$VP" 2>&1)" || rc=$?
rc_is $rc 1 "orphan table row (no persona file) exits nonzero"
has "orphan row" "$vout" "orphan row named in output"
vp_fixture "$VP" '| adv | Adversarial | Sonnet 4.6 |' '| adv | `adversarial.md` | `claude-haiku-4-5` |'
rc=0; vout="$("$DIR/validate-personas.py" --skill-dir "$VP" 2>&1)" || rc=$?
rc_is $rc 1 "tier mismatch between SKILL and unattended exits nonzero"
has "tier drift" "$vout" "tier drift named in output"
vp_fixture "$VP" '| adv | Adversarial | GPT-9000 |' '| adv | `adversarial.md` | `gpt-9000` |'
rc=0; vout="$("$DIR/validate-personas.py" --skill-dir "$VP" 2>&1)" || rc=$?
rc_is $rc 1 "unrecognized model string exits nonzero (TIER_RE blind spot)"
has "unrecognized model" "$vout" "unrecognized model named, not silently dropped"
# Frontmatter-contract fixtures: dead key and missing context key both fire.
vp_fixture "$VP" '| adv | Adversarial | Sonnet 4.6 |' '| adv | `adversarial.md` | `claude-sonnet-4-6` |'
mk_persona "$VP/personas/adversarial.md"
sed -i '/^experimental:/a prefers: []' "$VP/personas/adversarial.md"
rc=0; vout="$("$DIR/validate-personas.py" --skill-dir "$VP" 2>&1)" || rc=$?
rc_is $rc 1 "dead prefers: frontmatter key exits nonzero"
has "prefers" "$vout" "prefers: violation named in output"
vp_fixture "$VP" '| adv | Adversarial | Sonnet 4.6 |' '| adv | `adversarial.md` | `claude-sonnet-4-6` |'
mk_persona "$VP/personas/adversarial.md"
sed -i '/^  full_bundle:/d' "$VP/personas/adversarial.md"
rc=0; vout="$("$DIR/validate-personas.py" --skill-dir "$VP" 2>&1)" || rc=$?
rc_is $rc 1 "missing context key exits nonzero"
has "full_bundle" "$vout" "missing context key named in output"

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
lineM="$("$DIR/append-usage-log.sh" "$RDM" 2>/dev/null)" || true
has "usage.json-missing" "$lineM" "missing usage.json -> fallback line"
has "run:$RDM" "$lineM" "fallback line still carries run: pointer"
RDX="$ANGEL_RUNS_ROOT/r_bad"; mkdir -p "$RDX/findings"; echo '{bad json' > "$RDX/usage.json"
lineX="$("$DIR/append-usage-log.sh" "$RDX" 2>/dev/null)" || true
has "usage.json-malformed" "$lineX" "malformed usage.json -> fallback line"
# f10: a `|` in project/mode/persona must not shift the pipe-delimited columns
RDP="$ANGEL_RUNS_ROOT/r_pipe"; mkdir -p "$RDP/findings"
cat > "$RDP/usage.json" <<JSON
{"run_dir":"$RDP","project":"we|ird","mode":"fu|ll","reader_enabled":false,
 "started_at":"2026-05-31T12:00:00Z","ended_at":"2026-05-31T12:05:00Z",
 "totals":{"total_tokens":1000,"wall_seconds":10,
   "personas":[{"name":"rt|fm","model":"claude-sonnet-4-6","total_tokens":1000,"reader_pack":false}]},
 "unmeasured":[],"verdict":"OK","findings":{"critical":0,"important":0,"minor":0,"noted":0}}
JSON
lineP="$("$DIR/append-usage-log.sh" "$RDP")"
nf="$(printf '%s' "$lineP" | awk -F'|' '{print NF}')"
[ "$nf" = 7 ] && ok "pipe in project/mode/persona keeps 7 fields" || bad "pipe in project/mode/persona keeps 7 fields" "got $nf fields: $lineP"
has "we ird" "$lineP" "pipe in project replaced with space"
has "rt fm" "$lineP" "pipe in persona name replaced with space"

echo "== record-disposition.py =="
rc=0; "$DIR/record-disposition.py" "$RD" f1 accepted >/dev/null || rc=$?; rc_is $rc 0 "record accepted ok"
rc=0; "$DIR/record-disposition.py" "$RD" f4 rejected-wrong not a real bug at all >/dev/null || rc=$?; rc_is $rc 0 "record rejected-wrong ok"
note="$(python3 -c "import json;print(json.load(open('$RD/dispositions.json'))['f4']['note'])")"
[ "$note" = "not a real bug at all" ] && ok "note joins unquoted words" || bad "note joins unquoted words" "got: $note"
rc=0; "$DIR/record-disposition.py" "$RD" f9 bogus-disp 2>/dev/null || rc=$?; rc_is $rc 1 "invalid disposition rejected"
rc=0; "$DIR/record-disposition.py" /etc f1 accepted 2>/dev/null || rc=$?; rc_is $rc 1 "write outside runs-root rejected"

echo "== mine-runs.py (evidence + precision + overlap) =="
mk_snapshot "$RD"; echo "stub" > "$RD/findings/rtfm.md"
mout="$("$DIR/mine-runs.py" --runs-dir "$ANGEL_RUNS_ROOT" --since 2026-05-31)"
has "cited%" "$mout" "value table has cited% column"
has "fp% (n)" "$mout" "value table has fp% column"
has "Persona overlap" "$mout" "overlap section emitted"
has "adv + rtfm" "$mout" "overlap lists the shared-Important+ pair"
mjson="$("$DIR/mine-runs.py" --runs-dir "$ANGEL_RUNS_ROOT" --since 2026-05-31 --json)"
rc=0; python3 - "$mjson" <<'PY' || rc=$?
import json,sys
d=json.loads(sys.argv[1])
rt=d["personas"]["rtfm"]
assert rt["disposed"]==2, rt           # f1 + f4 dispositioned
assert rt["false_positives"]==1, rt    # f4 rejected-wrong
assert rt["cited"]>=1, rt              # f1 cited-spec
assert any(o["pair"]==["adv","rtfm"] for o in d["portfolio"]["overlap_important_plus"]), d["portfolio"]["overlap_important_plus"]
print("json-asserts-ok")
PY
rc_is $rc 0 "mine-runs --json: disposed/fp/cited/overlap correct"

echo "== check-run-complete.py =="
"$DIR/append-usage-log.sh" "$RD" >/dev/null   # ensures a run: line in $ANGEL_USAGE_LOG
rc=0; "$DIR/check-run-complete.py" "$RD" >/dev/null 2>&1 || rc=$?; rc_is $rc 0 "complete run passes"
rc=0; "$DIR/check-run-complete.py" "$RDN" >/dev/null 2>&1 || rc=$?; rc_is $rc 1 "incomplete run fails (no findings/snapshot)"
rc=0; "$DIR/check-run-complete.py" --all >/dev/null 2>&1 || rc=$?; rc_is $rc 1 "--all exits nonzero when any run incomplete"

# multiball completeness: a run with multiball N>=2 must persist within_persona_runs
RMB="$ANGEL_RUNS_ROOT/r_mball"; mk_usage "$RMB" 90000; echo "stub" > "$RMB/findings/adv_ball1.md"
"$DIR/append-usage-log.sh" "$RMB" >/dev/null
cat > "$RMB/findings-snapshot.json" <<'JSON'
{"version":2,"project":"demo","mode":"diff","multiball":2,"personas_run":["adv"],
 "findings":[{"id":"f1","severity":"important","title":"x","personas":["adv"]}],
 "within_persona_runs":null}
JSON
rc=0; "$DIR/check-run-complete.py" "$RMB" >/dev/null 2>&1 || rc=$?; rc_is $rc 1 "multiball run with null within_persona_runs fails"
ferr="$("$DIR/check-run-complete.py" "$RMB" 2>&1 || true)"; has "within_persona_runs" "$ferr" "failure names the missing per-pass record"
# now with a well-formed per-pass record it passes
cat > "$RMB/findings-snapshot.json" <<'JSON'
{"version":2,"project":"demo","mode":"diff","multiball":2,"personas_run":["adv"],
 "findings":[{"id":"f1","severity":"important","title":"x","personas":["adv"]}],
 "within_persona_runs":{"adv":[[{"severity":"important","title":"x","file":"a.ts"}],[{"severity":"important","title":"x","file":"a.ts"}]]}}
JSON
rc=0; "$DIR/check-run-complete.py" "$RMB" >/dev/null 2>&1 || rc=$?; rc_is $rc 0 "multiball run with valid within_persona_runs passes"
# prose-string record (the 2026-06-19 failure shape) must NOT pass as structured
cat > "$RMB/findings-snapshot.json" <<'JSON'
{"version":2,"project":"demo","mode":"diff","multiball":2,"personas_run":["adv"],
 "findings":[{"id":"f1","severity":"important","title":"x","personas":["adv"]}],
 "within_persona_runs":{"adv":["near-universal across all balls","adv balls 1 & 2"]}}
JSON
rc=0; "$DIR/check-run-complete.py" "$RMB" >/dev/null 2>&1 || rc=$?; rc_is $rc 1 "multiball run with prose-string within_persona_runs fails (not structured per-pass)"
# all-clean multiball run (both passes empty) is a VALID record — must pass
cat > "$RMB/findings-snapshot.json" <<'JSON'
{"version":2,"project":"demo","mode":"diff","multiball":2,"personas_run":["adv"],
 "findings":[],"within_persona_runs":{"adv":[[],[]]}}
JSON
rc=0; "$DIR/check-run-complete.py" "$RMB" >/dev/null 2>&1 || rc=$?; rc_is $rc 0 "multiball run with empty-but-structured passes ([[],[]]) passes (legit all-clean run)"
# empty within_persona_runs dict must fail
cat > "$RMB/findings-snapshot.json" <<'JSON'
{"version":2,"project":"demo","mode":"diff","multiball":2,"personas_run":["adv"],
 "findings":[],"within_persona_runs":{}}
JSON
rc=0; "$DIR/check-run-complete.py" "$RMB" >/dev/null 2>&1 || rc=$?; rc_is $rc 1 "multiball run with empty within_persona_runs dict fails"
# ball-file fallback: multiball inferred from *_ball*.md even if snapshot lacks the field, single-pass unaffected
cat > "$RMB/findings-snapshot.json" <<'JSON'
{"version":2,"project":"demo","mode":"diff","personas_run":["adv"],
 "findings":[{"id":"f1","severity":"important","title":"x","personas":["adv"]}],"within_persona_runs":null}
JSON
echo "stub" > "$RMB/findings/adv_ball2.md"
rc=0; "$DIR/check-run-complete.py" "$RMB" >/dev/null 2>&1 || rc=$?; rc_is $rc 1 "multiball inferred from ball files (no multiball field) still requires the record"
# bool multiball:true falls through to ball-file inference (not treated as N>=2 directly)
cat > "$RMB/findings-snapshot.json" <<'JSON'
{"version":2,"project":"demo","mode":"diff","multiball":true,"personas_run":["adv"],
 "findings":[],"within_persona_runs":{"adv":[[],[]]}}
JSON
rc=0; "$DIR/check-run-complete.py" "$RMB" >/dev/null 2>&1 || rc=$?; rc_is $rc 0 "multiball:true (bool) with valid record passes; bool not miscounted as N"

echo "== record-dispatch =="
RRD="$ANGEL_RUNS_ROOT/r_rd"; mkdir -p "$RRD"
rdl="$(printf '## Findings\n- one\n' | "$DIR/record-dispatch.sh" --findings "$RRD" persona rtfm claude-sonnet-4-6 50000 10 60000)"
rc=0; python3 - "$RRD" "$rdl" <<'PY' || rc=$?
import json, sys
rd, line = sys.argv[1], sys.argv[2]
j = json.loads(line)
assert j == {"phase": "persona", "name": "rtfm", "model": "claude-sonnet-4-6",
             "total_tokens": 50000, "tool_uses": 10, "duration_ms": 60000,
             "started_at": None, "ended_at": None, "reader_pack": False}, j
last = open(rd + "/usage.jsonl").read().strip().splitlines()[-1]
assert json.loads(last) == j, last
print("rd-asserts-ok")
PY
rc_is $rc 0 "record-dispatch appends a schema-correct JSONL line"
grep -q '^- one$' "$RRD/findings/rtfm.md" && ok "findings file written from stdin (--findings)" || bad "findings file written from stdin (--findings)"
rdn="$("$DIR/record-dispatch.sh" "$RRD" persona adv claude-sonnet-4-6 null null null unmeasured </dev/null)"
has '"total_tokens":null' "$rdn" "null tokens stay null in the JSONL line"
has '"note":"unmeasured"' "$rdn" "optional note arg lands on the line"
rdr="$("$DIR/record-dispatch.sh" --reader-pack "$RRD" persona hyper claude-sonnet-4-6 100 1 100 </dev/null)"
has '"reader_pack":true' "$rdr" "--reader-pack sets reader_pack:true"
rc=0; "$DIR/record-dispatch.sh" "$RRD" persona '../evil' m null null null </dev/null >/dev/null 2>&1 || rc=$?
rc_is $rc 1 "path-traversal persona name rejected (f34)"
rc=0; "$DIR/record-dispatch.sh" "$RRD" persona 'Bad Name' m null null null </dev/null >/dev/null 2>&1 || rc=$?
rc_is $rc 1 "non-[a-z0-9_-] persona name rejected"
rc=0; "$DIR/record-dispatch.sh" "$RRD" bogus rtfm m null null null </dev/null >/dev/null 2>&1 || rc=$?
rc_is $rc 1 "unknown phase rejected"
rc=0; "$DIR/record-dispatch.sh" "$RRD" persona rtfm m 12x3 null null </dev/null >/dev/null 2>&1 || rc=$?
rc_is $rc 1 "non-integer token count rejected"

echo "== init-run.sh =="
SYNTH_PROJ="$TMP/proj"; mkdir -p "$SYNTH_PROJ"
rc=0; iout="$(HOME="$TMP/home" "$DIR/init-run.sh" "$SYNTH_PROJ")" || rc=$?
rc_is $rc 0 "init-run exits 0"
[ "$(printf '%s\n' "$iout" | wc -l)" -eq 3 ] && ok "init-run emits exactly 3 stdout lines" || bad "init-run emits exactly 3 stdout lines" "got: $iout"
RUN_DIR=""; ENCODED_CWD=""; HANDOFF_DIR=""
eval "$iout"
[ -d "$RUN_DIR/findings" ] && ok "RUN_DIR/findings created" || bad "RUN_DIR/findings created" "RUN_DIR=$RUN_DIR"
[ -f "$RUN_DIR/usage.jsonl" ] && [ ! -s "$RUN_DIR/usage.jsonl" ] && ok "usage.jsonl created empty" || bad "usage.jsonl created empty"
case "$RUN_DIR" in "$ANGEL_RUNS_ROOT"/*) ok "RUN_DIR under ANGEL_RUNS_ROOT";; *) bad "RUN_DIR under ANGEL_RUNS_ROOT" "RUN_DIR=$RUN_DIR";; esac
[ "$ENCODED_CWD" = "${SYNTH_PROJ//\//-}" ] && ok "ENCODED_CWD encodes project dir" || bad "ENCODED_CWD encodes project dir" "got: $ENCODED_CWD"
[ -d "$HANDOFF_DIR" ] && ok "HANDOFF_DIR exists" || bad "HANDOFF_DIR exists" "got: $HANDOFF_DIR"
case "$HANDOFF_DIR" in "$TMP/home"/*) ok "HANDOFF_DIR honors HOME override (nothing outside temp)";; *) bad "HANDOFF_DIR honors HOME override" "got: $HANDOFF_DIR";; esac

echo "== aggregate-usage.py =="
RAG="$ANGEL_RUNS_ROOT/20260601T120000Z-fixture1"
mkdir -p "$RAG/findings"; echo "stub" > "$RAG/findings/rtfm.md"
cat > "$RAG/usage.jsonl" <<'JSONL'
{"phase":"persona","name":"rtfm","model":"claude-sonnet-4-6","total_tokens":50000,"tool_uses":10,"duration_ms":60000,"started_at":"2026-06-01T12:05:00Z","ended_at":"2026-06-01T12:06:00Z","reader_pack":false}
{"phase":"persona","name":"adv","model":"claude-sonnet-4-6","total_tokens":null,"tool_uses":null,"duration_ms":null,"reader_pack":false,"note":"unmeasured"}
{"phase":"integrator","name":"integrator","model":"claude-fable-5[1m]","total_tokens":20000,"tool_uses":0,"duration_ms":120000,"started_at":"2026-06-01T12:10:00Z","ended_at":"2026-06-01T12:12:00Z","reader_pack":false}
JSONL
mk_snapshot "$RAG"
rc=0; python3 "$DIR/aggregate-usage.py" "$RAG" >/dev/null 2>&1 || rc=$?; rc_is $rc 0 "aggregate-usage exits 0"
rc=0; python3 - "$RAG" <<'PY' || rc=$?
import json, sys
rd = sys.argv[1]
u = json.load(open(rd + "/usage.json"))
assert u["totals"]["total_tokens"] == 70000, u["totals"]["total_tokens"]   # null-safe sum
assert u["unmeasured"] == ["persona:adv"], u["unmeasured"]
assert u["totals"]["integrator"]["total_tokens"] == 20000, u["totals"]["integrator"]
assert u["totals"]["reader"] is None and u["reader_enabled"] is False, u
assert u["verdict"] == "CHANGES REQUIRED", u["verdict"]
assert u["findings"] == {"critical": 1, "important": 2, "minor": 1, "noted": 0}, u["findings"]
assert u["started_at"] == "2026-06-01T12:00:00Z", u["started_at"]          # from run-dir basename
assert u["totals"]["wall_seconds"] == 720, u["totals"]["wall_seconds"]
assert len(u["totals"]["personas"]) == 2, u["totals"]["personas"]
print("aggregate-asserts-ok")
PY
rc_is $rc 0 "aggregate-usage: totals/unmeasured/integrator/verdict/findings correct"
grep -q "persona:adv" "$RAG/UNMEASURED.md" && ok "UNMEASURED.md written with unmeasured entry" || bad "UNMEASURED.md written with unmeasured entry"

echo "== finalize-run.sh =="
rc=0; "$DIR/finalize-run.sh" "$RAG" >/dev/null 2>&1 || rc=$?; rc_is $rc 0 "finalize-run exits 0 on complete fixture"
grep -q "run:$RAG" "$ANGEL_USAGE_LOG" && ok "finalize-run appended usage.log line" || bad "finalize-run appended usage.log line"
RBAD="$ANGEL_RUNS_ROOT/20260601T130000Z-fixture2"   # no findings-snapshot.json -> completeness gate fails
mkdir -p "$RBAD/findings"; echo "stub" > "$RBAD/findings/rtfm.md"; : > "$RBAD/usage.jsonl"
rc=0; ferr="$("$DIR/finalize-run.sh" "$RBAD" 2>&1 >/dev/null)" || rc=$?
[ "$rc" -ne 0 ] && ok "finalize-run exits nonzero on incomplete fixture" || bad "finalize-run exits nonzero on incomplete fixture"
has "check-run-complete" "$ferr" "finalize-run stderr names the failing stage"

echo "== finalize-calibration =="
FC_HOME="$TMP/fchome"; mkdir -p "$FC_HOME"
FCLOG="$TMP/fc-usage.log"
FCB="$ANGEL_RUNS_ROOT/fc_base"; FCR="$ANGEL_RUNS_ROOT/fc_read"
mk_usage "$FCB" 100000; mk_snapshot "$FCB"
mk_usage "$FCR" 120000; mk_snapshot "$FCR"
cat > "$FCLOG" <<EOF
2026-05-31 | fcproj | full | 1C/2I/0M/1N | total:100000 | cal:baseline | run:$FCB
2026-05-31 | fcproj | full | 1C/2I/0M/1N | total:120000 | cal:reader | run:$FCR
EOF
FCROOT="$TMP/fcroot"; mkdir -p "$FCROOT/fcproj"
rc=0; fout="$(HOME="$FC_HOME" ANGEL_USAGE_LOG="$FCLOG" "$DIR/finalize-calibration.py" 2>&1)" || rc=$?
rc_is $rc 0 "finalize-calibration dry-run exits 0 on fixture log"
has "tok=+20.0%" "$fout" "dry-run pairs baseline+reader and computes token delta"
rc=0; fskip="$(HOME="$FC_HOME" ANGEL_USAGE_LOG="$FCLOG" "$DIR/finalize-calibration.py" --write 2>&1)" || rc=$?
has "no dir under $FC_HOME/Projects" "$fskip" "marker-skip message names the searched root"
rc=0; HOME="$FC_HOME" ANGEL_USAGE_LOG="$FCLOG" "$DIR/finalize-calibration.py" --write --projects-root "$FCROOT" >/dev/null 2>&1 || rc=$?
rc_is $rc 0 "--projects-root override accepted"
FC_ENC="${FCROOT//\//-}-fcproj"
FC_MARK="$FC_HOME/.claude/projects/$FC_ENC/memory/reader-calibration.json"
[ -f "$FC_MARK" ] && ok "marker written for project under overridden root" || bad "marker written for project under overridden root" "missing $FC_MARK"
rm -rf "$FC_HOME/.claude/projects"
HOME="$FC_HOME" ANGEL_USAGE_LOG="$FCLOG" ANGEL_PROJECTS_ROOT="$FCROOT" "$DIR/finalize-calibration.py" --write >/dev/null 2>&1 || true
[ -f "$FC_MARK" ] && ok "ANGEL_PROJECTS_ROOT env override honored" || bad "ANGEL_PROJECTS_ROOT env override honored" "missing $FC_MARK"
# f8: two DIFFERENT same-file findings with NO line numbers must not collapse into
# one match (line defaults to 0; 0==0 used to satisfy the file-line branch).
F8B="$ANGEL_RUNS_ROOT/f8_base"; F8R="$ANGEL_RUNS_ROOT/f8_read"
mk_usage "$F8B" 100000; mk_usage "$F8R" 100000
cat > "$F8B/findings-snapshot.json" <<'JSON'
{"version":1,"findings":[
 {"id":"a","severity":"critical","title":"unchecked deserialization of payload","file":"src/app.py","personas":["adv"]},
 {"id":"b","severity":"critical","title":"missing auth on admin route","file":"src/app.py","personas":["rtfm"]}
]}
JSON
cat > "$F8R/findings-snapshot.json" <<'JSON'
{"version":1,"findings":[
 {"id":"a","severity":"critical","title":"unchecked deserialization of payload","file":"src/app.py","personas":["adv"]}
]}
JSON
F8LOG="$TMP/f8-usage.log"
cat > "$F8LOG" <<EOF
2026-05-31 | f8proj | full | 2C/0I/0M/0N | total:100000 | cal:baseline | run:$F8B
2026-05-31 | f8proj | full | 1C/0I/0M/0N | total:100000 | cal:reader | run:$F8R
EOF
rc=0; f8out="$(HOME="$FC_HOME" ANGEL_USAGE_LOG="$F8LOG" "$DIR/finalize-calibration.py" 2>&1)" || rc=$?
rc_is $rc 0 "f8 fixture dry-run exits 0"
has "lostC=1" "$f8out" "distinct same-file no-line findings do NOT collapse (dropped critical counts as lost)"
has "gainC=0" "$f8out" "same-file same-title no-line finding still matches (not gained)"

echo
echo "--- subsample-analyzer + shared matcher suite (test_subsample.py) ---"
rc=0; python3 "$DIR/test_subsample.py" || rc=$?
rc_is $rc 0 "subsample-analyzer + finding_match suite passes"

echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
