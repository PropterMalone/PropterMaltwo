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
# opus vs sonnet, not haiku: haiku is no longer a recognized tier (ADR-21), so a
# haiku id here would trip the unrecognized-model check before the drift check.
vp_fixture "$VP" '| adv | Adversarial | Sonnet 4.6 |' '| adv | `adversarial.md` | `claude-opus-4-6` |'
rc=0; vout="$("$DIR/validate-personas.py" --skill-dir "$VP" 2>&1)" || rc=$?
rc_is $rc 1 "tier mismatch between SKILL and unattended exits nonzero"
has "tier drift" "$vout" "tier drift named in output"
vp_fixture "$VP" '| adv | Adversarial | Sonnet 4.6 |' '| adv | `adversarial.md` | `claude-haiku-4-5` |'
rc=0; vout="$("$DIR/validate-personas.py" --skill-dir "$VP" 2>&1)" || rc=$?
rc_is $rc 1 "haiku row in a model table exits nonzero (ADR-21)"
has "haiku retired" "$vout" "haiku retirement named in output"
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
# Value-enum fixtures (F2): default ∈ {yes,opt-in}, experimental ∈ {true,false}, modes ⊆ {diff,full}
vp_fixture "$VP" '| adv | Adversarial | Sonnet 4.6 |' '| adv | `adversarial.md` | `claude-sonnet-4-6` |'
mk_persona "$VP/personas/adversarial.md"
sed -i 's/^default: yes/default: no/' "$VP/personas/adversarial.md"
rc=0; vout="$("$DIR/validate-personas.py" --skill-dir "$VP" 2>&1)" || rc=$?
rc_is $rc 1 "invalid default value (no) exits nonzero"
has "default" "$vout" "invalid default value named in output"
vp_fixture "$VP" '| adv | Adversarial | Sonnet 4.6 |' '| adv | `adversarial.md` | `claude-sonnet-4-6` |'
mk_persona "$VP/personas/adversarial.md"
sed -i 's/^experimental: false/experimental: maybe/' "$VP/personas/adversarial.md"
rc=0; vout="$("$DIR/validate-personas.py" --skill-dir "$VP" 2>&1)" || rc=$?
rc_is $rc 1 "invalid experimental value (maybe) exits nonzero"
has "experimental" "$vout" "invalid experimental value named in output"
vp_fixture "$VP" '| adv | Adversarial | Sonnet 4.6 |' '| adv | `adversarial.md` | `claude-sonnet-4-6` |'
mk_persona "$VP/personas/adversarial.md"
sed -i 's/^modes: \[diff, full\]/modes: [diff, full, bogus]/' "$VP/personas/adversarial.md"
rc=0; vout="$("$DIR/validate-personas.py" --skill-dir "$VP" 2>&1)" || rc=$?
rc_is $rc 1 "invalid modes value (bogus) exits nonzero"
has "modes" "$vout" "invalid modes value named in output"
# Signal-parity fixture (F4): validate-personas detects signals in SKILL.md §1.5 missing from unattended.md
# Build SKILL.md with the model table (so model-parity checks pass) + a §1.5 signal table with prose_artifacts.
# Build unattended.md with the model table + a Step 2.5 signal table that OMITS prose_artifacts.
vp4="$TMP/vp4"; rm -rf "$vp4"; mkdir -p "$vp4/personas"
mk_persona "$vp4/personas/adversarial.md"
cat > "$vp4/SKILL.md" <<'MD'
# fixture

## 1. Parse arguments

| Short | Full | Model |
|-------|------|-------|
| adv | Adversarial | Sonnet 4.6 |

## 1.5. Battery selection

| Signal | Concept (with example hints — non-exhaustive) |
|--------|-----------------------------------------------|
| `any` | Always present. |
| `prose_artifacts` | Predominantly prose change or project. |
MD
cat > "$vp4/unattended.md" <<'MD'
# fixture

## Step 3: Dispatch personas

| Short | Persona file | Model |
|-------|-------------|-------|
| adv | `adversarial.md` | `claude-sonnet-4-6` |

## Step 2.5: Battery selection

| Signal | Concept (with example hints — non-exhaustive) |
|--------|-----------------------------------------------|
| `any` | Always present. |
MD
rc=0; vout="$("$DIR/validate-personas.py" --skill-dir "$vp4" 2>&1)" || rc=$?
rc_is $rc 1 "signal parity: prose_artifacts in SKILL but not unattended exits nonzero"
has "prose_artifacts" "$vout" "signal parity: missing signal named in output"

# Dispatch-block parity (ADR-15 f17). A persona needing an orchestrator-composed
# context block must have it documented on BOTH paths; a block on one path only
# leaves that persona run-blind on the other. These fixtures prove the check
# fires rather than passing vacuously on the live tree.
vp5="$TMP/vp5"; rm -rf "$vp5"; mkdir -p "$vp5/personas"
mk_persona "$vp5/personas/recipient.md"
cat > "$vp5/SKILL.md" <<'MD'
# fixture

| Short | Full | Model |
|---|---|---|
| recip | Recipient | Fable 5 |

Compose an <artifact_paths> block for recip before dispatching.
MD
cat > "$vp5/unattended.md" <<'MD'
# fixture

## Step 3: Dispatch personas

| Short | Persona file | Model |
|-------|-------------|-------|
| recip | `recipient.md` | `claude-fable-5` |
MD
rc=0; vout="$("$DIR/validate-personas.py" --skill-dir "$vp5" 2>&1)" || rc=$?
rc_is $rc 1 "block parity: recip's artifact_paths in SKILL but not unattended exits nonzero"
has "artifact_paths" "$vout" "block parity: missing block named in output"
has "recip" "$vout" "block parity: owning persona named in output"

# Same fixture, block now documented on both paths -> clean.
printf 'Compose an <artifact_paths> block for recip before dispatching.\n' >> "$vp5/unattended.md"
rc=0; vout="$("$DIR/validate-personas.py" --skill-dir "$vp5" 2>&1)" || rc=$?
rc_is $rc 0 "block parity: block on both paths is clean"

# Shared-tag fixture (ADR-16 review, f1). recip and orgpolicy both need
# <artifact_paths>. unattended.md documents it for recip only, so orgpolicy is
# run-blind there even though the tag appears elsewhere in the file.
vp7="$TMP/vp7"; rm -rf "$vp7"; mkdir -p "$vp7/personas"
mk_persona "$vp7/personas/recipient.md"
mk_persona "$vp7/personas/organization-policy.md"
cat > "$vp7/SKILL.md" <<'MD'
# fixture

| Short | Full | Model |
|---|---|---|
| recip | Recipient | Fable 5 |
| orgpolicy | Org-Policy | Fable 5 |

When composing the prompt for recip, append an <artifact_paths> block.

When composing the prompt for orgpolicy, append a <policy_index> block.

orgpolicy also receives an <artifact_paths> block when artifacts are supplied.
MD
cat > "$vp7/unattended.md" <<'MD'
# fixture

## Step 3: Dispatch personas

| Short | Persona file | Model |
|-------|-------------|-------|
| recip | `recipient.md` | `claude-fable-5` |
| orgpolicy | `organization-policy.md` | `claude-fable-5` |

When composing the prompt for recip, append an <artifact_paths> block.

When composing the prompt for orgpolicy, append a <policy_index> block.
MD
rc=0; vout="$("$DIR/validate-personas.py" --skill-dir "$vp7" 2>&1)" || rc=$?
rc_is $rc 1 "block parity: shared tag documented for recip only exits nonzero"
has "'orgpolicy' needs <artifact_paths>" "$vout" "block parity: unscoped-tag drift names orgpolicy, not recip"
printf '\norgpolicy also receives an <artifact_paths> block when artifacts are supplied.\n' >> "$vp7/unattended.md"
rc=0; vout="$("$DIR/validate-personas.py" --skill-dir "$vp7" 2>&1)" || rc=$?
rc_is $rc 0 "block parity: shared tag documented for both personas is clean"

# Coverage fixture (ADR-16 review, f7). A persona whose own file tells its leaf to
# read an orchestrator-composed block, but which was never added to DISPATCH_BLOCKS.
# The parity loop only iterates the dict, so the pre-fix validator reports clean and
# that persona's block is unchecked on both paths forever.
vp8="$TMP/vp8"; vp_fixture "$vp8" '| adv | Adversarial | Sonnet 4.6 |' '| adv | `adversarial.md` | `claude-sonnet-4-6` |'
mk_persona "$vp8/personas/adversarial.md"
printf '\nYou will receive a <ghost_registry> block carrying absolute paths. Read it first.\n' >> "$vp8/personas/adversarial.md"
rc=0; vout="$("$DIR/validate-personas.py" --skill-dir "$vp8" 2>&1)" || rc=$?
rc_is $rc 1 "block coverage: unregistered block in a persona file exits nonzero"
has "block coverage" "$vout" "block coverage: the unregistered block is named"
has "ghost_registry" "$vout" "block coverage: names the tag the persona reads"
# An <example>-style markup tag is not a dispatch block and must not fire.
mk_persona "$vp8/personas/adversarial.md"
printf '\nSee <example> for the shape of a good finding.\n' >> "$vp8/personas/adversarial.md"
rc=0; vout="$("$DIR/validate-personas.py" --skill-dir "$vp8" 2>&1)" || rc=$?
rc_is $rc 0 "block coverage: a non-block markup tag does not fire"

# A persona absent from the roster carries no block requirement (retirement).
vp6="$TMP/vp6"; vp_fixture "$vp6" '| adv | Adversarial | Sonnet 4.6 |' '| adv | `adversarial.md` | `claude-sonnet-4-6` |'
mk_persona "$vp6/personas/adversarial.md"
rc=0; vout="$("$DIR/validate-personas.py" --skill-dir "$vp6" 2>&1)" || rc=$?
rc_is $rc 0 "block parity: retired persona's block requirement retires with it"

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

# Regression: a re-finalize must SUPERSEDE its earlier line, not append a second.
# Appending before the completeness gate allowed duplicate and premature zero-count
# records, which cross-run precision mining could misread as "found nothing."
RDUP="$ANGEL_RUNS_ROOT/r_dup"; mkdir -p "$RDUP/findings"
mk_dup_usage() { # $1=critical $2=important
  cat > "$RDUP/usage.json" <<JSON
{"run_dir":"$RDUP","project":"dupdemo","mode":"diff","reader_enabled":false,
 "started_at":"2026-08-02T12:00:00Z","ended_at":"2026-08-02T12:05:00Z",
 "totals":{"total_tokens":1000,"wall_seconds":10,
   "personas":[{"name":"naive","model":"claude-sonnet-4-6","total_tokens":1000,"reader_pack":false}]},
 "unmeasured":[],"verdict":"CHANGES REQUIRED","findings":{"critical":$1,"important":$2,"minor":0,"noted":0}}
JSON
}
before_n="$(grep -c . "$ANGEL_USAGE_LOG" 2>/dev/null || echo 0)"
mk_dup_usage 0 0;  "$DIR/append-usage-log.sh" "$RDUP" >/dev/null 2>&1   # premature finalize
mk_dup_usage 2 10; "$DIR/append-usage-log.sh" "$RDUP" >/dev/null 2>&1   # re-finalize, complete
dup_lines="$(grep -c "run:$RDUP\$\|run:$RDUP " "$ANGEL_USAGE_LOG" || true)"
[ "$dup_lines" = 1 ] && ok "re-finalize supersedes (one line per run)" \
  || bad "re-finalize supersedes (one line per run)" "got $dup_lines lines for $RDUP"
dup_line="$(grep "run:$RDUP\$\|run:$RDUP " "$ANGEL_USAGE_LOG" | tail -1)"
has "2C/10I/0M/0N" "$dup_line" "later (complete) counts win over premature 0C/0I"
after_n="$(grep -c . "$ANGEL_USAGE_LOG")"
[ "$((after_n - before_n))" = 1 ] && ok "supersede leaves other runs' lines intact" \
  || bad "supersede leaves other runs' lines intact" "log grew by $((after_n - before_n)), expected 1"

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

# f15: --skill-dir canonicalization: a file-stem key (e.g. "adversarial") alongside
# the canonical short-name key (e.g. "adv") must merge into one row when the
# fixture personas dir maps stem -> canon (adversarial.md frontmatter name: adv).
MR_SKILL="$TMP/mr_skill"; mkdir -p "$MR_SKILL/personas"
# Write a persona where FILE STEM ("adversarial") differs from frontmatter name ("adv").
# build_persona_aliases maps both -> "adv"; so snapshots logging either key merge.
cat > "$MR_SKILL/personas/adversarial.md" <<'PERSONA'
---
name: adv
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
MR_RUNS="$TMP/mr_runs"; mkdir -p "$MR_RUNS"
# run-A: snapshot uses the long file-stem key "adversarial"
MR_A="$MR_RUNS/20260601T120000Z-mrA"; mkdir -p "$MR_A/findings"; echo "stub" > "$MR_A/findings/adversarial.md"
cat > "$MR_A/findings-snapshot.json" <<'JSON'
{"version":1,"project":"mrtest","date":"2026-06-01","mode":"full","verdict":"OK",
 "personas_run":["adversarial"],
 "findings":[{"id":"fa1","severity":"important","title":"Stem key finding","personas":["adversarial"],"evidence":"code-site"}]}
JSON
# run-B: snapshot uses the canonical short name "adv"
MR_B="$MR_RUNS/20260601T130000Z-mrB"; mkdir -p "$MR_B/findings"; echo "stub" > "$MR_B/findings/adv.md"
cat > "$MR_B/findings-snapshot.json" <<'JSON'
{"version":1,"project":"mrtest","date":"2026-06-01","mode":"full","verdict":"OK",
 "personas_run":["adv"],
 "findings":[{"id":"fb1","severity":"important","title":"Short name finding","personas":["adv"],"evidence":"code-site"}]}
JSON
mralias="$("$DIR/mine-runs.py" --runs-dir "$MR_RUNS" --since 2026-06-01 --skill-dir "$MR_SKILL" --json)"
rc=0; python3 - "$mralias" <<'PY' || rc=$?
import json, sys
d = json.loads(sys.argv[1])
# adversarial.md has name: adv -> both "adversarial" and "adv" canonicalize to "adv".
assert len(d["personas"]) == 1, f"expected 1 canonical persona row, got {list(d['personas'].keys())}"
key = list(d["personas"].keys())[0]
assert key == "adv", f"expected canonical key 'adv', got '{key}'"
assert d["personas"][key]["findings"] == 2, f"expected 2 merged findings, got {d['personas'][key]}"
print("alias-canon-ok")
PY
rc_is $rc 0 "mine-runs --skill-dir: file-stem key merges with canonical short name into one row"

# f17: REFUTED verdicts must count as false positives in per-persona precision.
# Run with a snapshot that has a REFUTED verification on adv's finding.
MR_REF="$ANGEL_RUNS_ROOT/20260602T120000Z-refuted"; mkdir -p "$MR_REF/findings"; echo "stub" > "$MR_REF/findings/adv.md"
cat > "$MR_REF/findings-snapshot.json" <<'JSON'
{"version":2,"project":"reftest","date":"2026-06-02","mode":"full","verdict":"CHANGES REQUIRED",
 "personas_run":["adv"],
 "findings":[
  {"id":"rf1","severity":"important","title":"Refuted finding","personas":["adv"],
   "verification":{"verdict":"REFUTED","method":"ran","evidence":"not reproducible"}},
  {"id":"rf2","severity":"important","title":"Confirmed finding","personas":["adv"],
   "verification":{"verdict":"CONFIRMED","method":"traced","evidence":"traced to sink"}}
 ]}
JSON
mrref_json="$("$DIR/mine-runs.py" --runs-dir "$ANGEL_RUNS_ROOT" --since 2026-06-02 --json)"
rc=0; python3 - "$mrref_json" <<'PY' || rc=$?
import json, sys
d = json.loads(sys.argv[1])
adv = d["personas"]["adv"]
# rf1 is REFUTED -> counts as machine FP; rf2 is CONFIRMED -> not FP.
assert adv["false_positives"] == 1, f"expected 1 REFUTED FP, got {adv}"
assert adv["machine_false_positives"] == 1, f"machine_false_positives must track REFUTED count: {adv}"
assert adv["human_false_positives"] == 0, f"human_false_positives must be 0 (no rejected-wrong): {adv}"
print("refuted-fp-ok")
PY
rc_is $rc 0 "mine-runs: REFUTED verdict counts as false positive in precision metric"

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
# a prose-string record must NOT pass as structured per-pass data
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

# MULTIBALL marker file detection
RMB2="$ANGEL_RUNS_ROOT/r_mball2"; mk_usage "$RMB2" 90000; echo "stub" > "$RMB2/findings/adv.md"
printf '2\n' > "$RMB2/MULTIBALL"
"$DIR/append-usage-log.sh" "$RMB2" >/dev/null
cat > "$RMB2/findings-snapshot.json" <<'JSON'
{"version":2,"project":"demo","mode":"diff","personas_run":["adv"],
 "findings":[],"within_persona_runs":null}
JSON
rc=0; "$DIR/check-run-complete.py" "$RMB2" >/dev/null 2>&1 || rc=$?; rc_is $rc 1 "MULTIBALL marker triggers within_persona_runs check"
# with valid within_persona_runs it passes
cat > "$RMB2/findings-snapshot.json" <<'JSON'
{"version":2,"project":"demo","mode":"diff","personas_run":["adv"],
 "findings":[],"within_persona_runs":{"adv":[[],[]]}}
JSON
rc=0; "$DIR/check-run-complete.py" "$RMB2" >/dev/null 2>&1 || rc=$?; rc_is $rc 0 "MULTIBALL marker + valid within_persona_runs passes"
# passes/ dir detection
RMB3="$ANGEL_RUNS_ROOT/r_mball3"; mk_usage "$RMB3" 90000; echo "stub" > "$RMB3/findings/adv.md"
mkdir -p "$RMB3/passes"; touch "$RMB3/passes/adv-p1.md" "$RMB3/passes/adv-p2.md"
"$DIR/append-usage-log.sh" "$RMB3" >/dev/null
cat > "$RMB3/findings-snapshot.json" <<'JSON'
{"version":2,"project":"demo","mode":"diff","personas_run":["adv"],
 "findings":[],"within_persona_runs":null}
JSON
rc=0; "$DIR/check-run-complete.py" "$RMB3" >/dev/null 2>&1 || rc=$?; rc_is $rc 1 "passes/ dir triggers within_persona_runs check"
cat > "$RMB3/findings-snapshot.json" <<'JSON'
{"version":2,"project":"demo","mode":"diff","personas_run":["adv"],
 "findings":[],"within_persona_runs":{"adv":[[],[]]}}
JSON
rc=0; "$DIR/check-run-complete.py" "$RMB3" >/dev/null 2>&1 || rc=$?; rc_is $rc 0 "passes/ dir + valid within_persona_runs passes"

# ADR-12: element-level check rejects id-ref strings (version-independent — catches the
# 3 broken 2026-07 inline snapshots on --all audits, no passes/ dir needed).
REL="$ANGEL_RUNS_ROOT/r_idref"; mk_usage "$REL" 50000; echo stub > "$REL/findings/adv.md"; "$DIR/append-usage-log.sh" "$REL" >/dev/null
cat > "$REL/findings-snapshot.json" <<'JSON'
{"project":"x","mode":"full","multiball":2,"findings":[],"within_persona_runs":{"adv":[["f1","f2","f3"],["f1","f2","f3"]]}}
JSON
rc=0; "$DIR/check-run-complete.py" "$REL" >/dev/null 2>&1 || rc=$?; rc_is $rc 1 "id-ref within_persona_runs rejected (element check, version-independent)"

# ADR-12: provenance gate — stored field must equal an assemble-wpr recompute from passes/.
RPV="$ANGEL_RUNS_ROOT/r_prov"; mk_usage "$RPV" 50000; echo stub > "$RPV/findings/adv.md"
mkdir -p "$RPV/passes"
printf '#### Critical (blocks ship)\n- **race in writer** `[moderate]` — `a.py:10` — boom\n' > "$RPV/passes/adv-p1.md"
printf '#### Critical (blocks ship)\n- **race in writer** `[moderate]` — `a.py:11` — boom\n' > "$RPV/passes/adv-p2.md"
"$DIR/append-usage-log.sh" "$RPV" >/dev/null
cat > "$RPV/findings-snapshot.json" <<'JSON'
{"project":"x","mode":"full","multiball":2,"findings":[],"within_persona_runs":{"adv":[[{"severity":"critical","title":"WRONG","file":"a.py","line":"10","rid":null,"model":null}],[{"severity":"critical","title":"WRONG2","file":"a.py","line":"11","rid":null,"model":null}]]}}
JSON
rc=0; "$DIR/check-run-complete.py" "$RPV" >/dev/null 2>&1 || rc=$?; rc_is $rc 1 "provenance mismatch (stored != recompute) rejected"
ferr="$("$DIR/check-run-complete.py" "$RPV" 2>&1 || true)"; has "provenance" "$ferr" "failure names provenance"
# now write the real field via assemble-wpr -> provenance passes
"$DIR/assemble-wpr.py" "$RPV" >/dev/null 2>&1 || true
rc=0; "$DIR/check-run-complete.py" "$RPV" >/dev/null 2>&1 || rc=$?; rc_is $rc 0 "provenance passes after assemble-wpr writes the field"

# ADR-12: incomplete-passes — a persona missing a pass under N (provenance still matches).
RIC="$ANGEL_RUNS_ROOT/r_incpass"; mk_usage "$RIC" 50000; echo stub > "$RIC/findings/adv.md"; printf '2\n' > "$RIC/MULTIBALL"
mkdir -p "$RIC/passes"
printf '#### Minor\n- **alpha bug** `[trivial]` — `x.py:1` — y\n' > "$RIC/passes/hyper-p1.md"
printf '#### Minor\n- **alpha bug** `[trivial]` — `x.py:2` — y\n' > "$RIC/passes/hyper-p2.md"
printf '#### Minor\n- **beta bug** `[trivial]` — `z.py:1` — y\n' > "$RIC/passes/adv-p1.md"   # adv-p2 MISSING
"$DIR/append-usage-log.sh" "$RIC" >/dev/null
printf '{"project":"x","mode":"full","multiball":2,"findings":[]}\n' > "$RIC/findings-snapshot.json"
"$DIR/assemble-wpr.py" "$RIC" >/dev/null 2>&1 || true
rc=0; "$DIR/check-run-complete.py" "$RIC" >/dev/null 2>&1 || rc=$?; rc_is $rc 1 "incomplete passes (adv missing p2, hyper complete) rejected"
ferr="$("$DIR/check-run-complete.py" "$RIC" 2>&1 || true)"; has "incomplete" "$ferr" "failure names incomplete passes"

echo "== record-dispatch =="
RRD="$ANGEL_RUNS_ROOT/r_rd"; mkdir -p "$RRD"
rdl="$(printf '## Findings\n- one\n' | "$DIR/record-dispatch.sh" --findings "$RRD" persona rtfm claude-sonnet-4-6 50000 10 60000)"
rc=0; python3 - "$RRD" "$rdl" <<'PY' || rc=$?
import json, re, sys
from datetime import datetime, timezone
rd, line = sys.argv[1], sys.argv[2]
j = json.loads(line)
# ADR-11: timestamps are real ISO-8601 strings, not null
assert j["phase"] == "persona", j
assert j["name"] == "rtfm", j
assert j["model"] == "claude-sonnet-4-6", j
assert j["total_tokens"] == 50000, j
assert j["tool_uses"] == 10, j
assert j["duration_ms"] == 60000, j
assert j["reader_pack"] == False, j
assert "backend" not in j, j
ISO_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
assert ISO_RE.match(j["ended_at"]), f"ended_at not ISO-8601: {j['ended_at']}"
assert ISO_RE.match(j["started_at"]), f"started_at not ISO-8601: {j['started_at']}"
# started_at == ended_at - 60s (duration_ms=60000)
ea = datetime.strptime(j["ended_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
sa = datetime.strptime(j["started_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
assert (ea - sa).total_seconds() == 60, f"expected 60s gap, got {(ea-sa).total_seconds()}"
last = open(rd + "/usage.jsonl").read().strip().splitlines()[-1]
assert json.loads(last) == j, last
print("rd-asserts-ok")
PY
rc_is $rc 0 "record-dispatch appends a schema-correct JSONL line"
rdbackend="$("$DIR/record-dispatch.sh" --backend codex "$RRD" persona adv gpt-5.6-sol 1234 null 50 </dev/null)"
has '"backend":"codex"' "$rdbackend" "--backend lands on the JSONL line"
rdlegacy="$("$DIR/record-dispatch.sh" "$RRD" persona adv gpt-5.6-sol 1234 null 50 </dev/null)"
hasnt '"backend"' "$rdlegacy" "omitted --backend leaves the field absent"
# null-duration dispatch: started_at must be null, ended_at must be ISO-8601
rdnull="$("$DIR/record-dispatch.sh" "$RRD" persona rtfm claude-sonnet-4-6 null null null </dev/null)"
rc=0; python3 - "$rdnull" <<'PY' || rc=$?
import json, re, sys
j = json.loads(sys.argv[1])
assert j["started_at"] is None, f"null-duration: started_at should be null, got {j['started_at']}"
ISO_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
assert ISO_RE.match(j["ended_at"]), f"null-duration: ended_at not ISO-8601: {j['ended_at']}"
print("null-duration-ok")
PY
rc_is $rc 0 "null-duration dispatch: started_at null, ended_at stamped"
grep -q '^- one$' "$RRD/findings/rtfm.md" && ok "findings file written from stdin (--findings)" || bad "findings file written from stdin (--findings)"
rdn="$("$DIR/record-dispatch.sh" "$RRD" persona adv claude-sonnet-4-6 null null null unmeasured </dev/null)"
has '"total_tokens":null' "$rdn" "null tokens stay null in the JSONL line"
has '"note":"unmeasured"' "$rdn" "optional note arg lands on the line"
rdr="$("$DIR/record-dispatch.sh" --reader-pack "$RRD" persona hyper claude-sonnet-4-6 100 1 100 </dev/null)"
has '"reader_pack":true' "$rdr" "--reader-pack sets reader_pack:true"
rc=0; "$DIR/record-dispatch.sh" "$RRD" persona '../evil' m null null null </dev/null >/dev/null 2>&1 || rc=$?
rc_is $rc 1 "path-traversal persona name rejected (f34)"
rc=0; "$DIR/record-dispatch.sh" "$RRD" persona 'Bad Name' m null null null </dev/null >/dev/null 2>&1 || rc=$?
rc_is $rc 1 "non-[A-Za-z0-9_-] persona name rejected"
rc=0; "$DIR/record-dispatch.sh" "$RRD" bogus rtfm m null null null </dev/null >/dev/null 2>&1 || rc=$?
rc_is $rc 1 "unknown phase rejected"
rdv="$("$DIR/record-dispatch.sh" "$RRD" verifier f3 claude-sonnet-4-6 7000 3 30000 </dev/null)"
has '"phase":"verifier"' "$rdv" "verifier phase accepted (verification stage)"
rc=0; "$DIR/record-dispatch.sh" "$RRD" persona rtfm m 12x3 null null </dev/null >/dev/null 2>&1 || rc=$?
rc_is $rc 1 "non-integer token count rejected"

# --- ADR-12: --pass / --failed / --verdict / multiball guard ---
RRD2="$ANGEL_RUNS_ROOT/r_rd2"; mkdir -p "$RRD2"
printf '#### Critical (blocks ship)\n- **race in writer** `[moderate]` — `a.py:10` — boom\n' \
  | "$DIR/record-dispatch.sh" --findings --pass 1 "$RRD2" persona adv claude-sonnet-5 100 1 100 >/dev/null
[ -f "$RRD2/passes/adv-p1.md" ] && ok "--pass 1 writes passes/adv-p1.md" || bad "--pass 1 writes passes/adv-p1.md"
grep -q 'angel-pass persona=adv pass=1 model=claude-sonnet-5' "$RRD2/passes/adv-p1.md" \
  && ok "--pass stamps the model header (D3)" || bad "--pass stamps the model header (D3)"
[ -f "$RRD2/findings/adv.md" ] && ok "--pass 1 --findings also writes findings/adv.md" || bad "--pass 1 --findings also writes findings/adv.md"
printf '#### Minor\n- **nit** `[trivial]` — `b.py:2` — x\n' \
  | "$DIR/record-dispatch.sh" --pass 2 "$RRD2" persona adv claude-sonnet-5 null null null >/dev/null
[ -f "$RRD2/passes/adv-p2.md" ] && ok "--pass 2 writes passes/adv-p2.md" || bad "--pass 2 writes passes/adv-p2.md"
# capture-time rejection of a no-structure block
rc=0; printf 'this is just prose with no finding structure at all\n' \
  | "$DIR/record-dispatch.sh" --pass 1 "$RRD2" persona naive m null null null >/dev/null 2>&1 || rc=$?
rc_is $rc 2 "no-structure pass block rejected (exit 2)"
[ -f "$RRD2/passes/naive-p1.md.rejected" ] && ok "rejected pass -> .rejected sidecar" || bad "rejected pass -> .rejected sidecar"
[ ! -f "$RRD2/passes/naive-p1.md" ] && ok "rejected pass NOT written as canonical" || bad "rejected pass NOT written as canonical"
# --failed excused stub
"$DIR/record-dispatch.sh" --failed --pass 3 "$RRD2" persona adv m null null null timeout >/dev/null
grep -q 'failed' "$RRD2/passes/adv-p3.md" && ok "--failed writes an excused failure stub" || bad "--failed writes an excused failure stub"
# --findings only composes with --pass 1
rc=0; printf 'x\n' | "$DIR/record-dispatch.sh" --findings --pass 2 "$RRD2" persona adv m null null null >/dev/null 2>&1 || rc=$?
rc_is $rc 1 "--findings with --pass 2 rejected"
# multiball guard
RRDMB="$ANGEL_RUNS_ROOT/r_rd_mb"; mkdir -p "$RRDMB"; printf '2\n' > "$RRDMB/MULTIBALL"
rc=0; "$DIR/record-dispatch.sh" "$RRDMB" persona adv m null null null </dev/null >/dev/null 2>&1 || rc=$?
rc_is $rc 1 "multiball persona dispatch without --pass rejected"
rc=0; printf '#### Minor\n- **x** `[trivial]` — `a.py:1` — y\n' \
  | "$DIR/record-dispatch.sh" --pass 1 "$RRDMB" persona adv m null null null >/dev/null 2>&1 || rc=$?
rc_is $rc 0 "multiball persona dispatch with --pass accepted"
rc=0; "$DIR/record-dispatch.sh" "$RRDMB" integrator integrator m null null null </dev/null >/dev/null 2>&1 || rc=$?
rc_is $rc 0 "non-persona phase exempt from the multiball --pass guard"
# --verdict folds the verifier hand-write into the chokepoint
printf '{"id":"C1","verdict":"CONFIRMED"}' | "$DIR/record-dispatch.sh" --verdict "$RRD2" verifier C1 m 100 1 100 >/dev/null
[ -f "$RRD2/verification/C1.json" ] && ok "--verdict writes verification/C1.json (mixed-case id)" || bad "--verdict writes verification/C1.json (mixed-case id)"
rc=0; printf 'not json' | "$DIR/record-dispatch.sh" --verdict "$RRD2" verifier C2 m null null null >/dev/null 2>&1 || rc=$?
rc_is $rc 1 "--verdict rejects a non-JSON payload"

echo "== dispatch-leg.sh =="
CODEX_SHIM="$TMP/codex-shim"; mkdir -p "$CODEX_SHIM"
cat > "$CODEX_SHIM/codex" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == "exec" ]]
printf '%s' "${!#}" > "$CODEX_ARG_CAPTURE"
cat > "$CODEX_STDIN_CAPTURE"
printf '%s\n' \
  'OpenAI Codex stub' \
  'model: gpt-5.6-sol' \
  'codex' \
  '## [Adversarial] Review' \
  '#### Important' \
  '- **stub finding** `[trivial]` — `stub.py:1` — exercised' \
  'tokens used' \
  '12,345'
SH
chmod +x "$CODEX_SHIM/codex"
RDL="$ANGEL_RUNS_ROOT/r_dispatch_leg"; mkdir -p "$RDL"
PROMPT_EXPECTED="$TMP/dispatch-prompt.expected"
PROMPT_ACTUAL="$TMP/dispatch-prompt.actual"
PROMPT_ARG="$TMP/dispatch-prompt.arg"
printf 'review this prompt\nwith a second line and no trailing newline' > "$PROMPT_EXPECTED"
rc=0; dlout="$(CODEX_BIN="$CODEX_SHIM/codex" CODEX_STDIN_CAPTURE="$PROMPT_ACTUAL" \
  CODEX_ARG_CAPTURE="$PROMPT_ARG" "$DIR/dispatch-leg.sh" \
  --run-dir "$RDL" --phase persona --name adv --model gpt-5.6-sol --pass 1 --findings \
  < "$PROMPT_EXPECTED" 2>&1)" || rc=$?
rc_is $rc 0 "dispatch-leg succeeds through a CODEX_BIN-shimmed codex"
[ "$(cat "$PROMPT_ARG")" = "-" ] && ok "dispatch-leg passes - as codex's prompt argument" || bad "dispatch-leg passes - as codex's prompt argument"
cmp -s "$PROMPT_EXPECTED" "$PROMPT_ACTUAL" && ok "dispatch-leg feeds the full prompt to codex on stdin" || bad "dispatch-leg feeds the full prompt to codex on stdin"
rc=0; python3 - "$RDL" <<'PY' || rc=$?
import json, sys
rd = sys.argv[1]
lines = [json.loads(x) for x in open(rd + "/usage.jsonl") if x.strip()]
assert len(lines) == 1, lines
line = lines[0]
assert line["total_tokens"] == 12345, line
assert line["backend"] == "codex", line
assert line["model"] == "gpt-5.6-sol", line
assert "requested=gpt-5.6-sol|ran=gpt-5.6-sol" in line["note"], line
print("dispatch-leg-ok")
PY
rc_is $rc 0 "dispatch-leg records tokens, codex backend, and requested/ran model"
[ -f "$RDL/passes/adv-p1.md" ] && ok "dispatch-leg writes the pass through record-dispatch" || bad "dispatch-leg writes the pass through record-dispatch"
[ -f "$RDL/findings/adv.md" ] && ok "dispatch-leg passes --findings through to record-dispatch" || bad "dispatch-leg passes --findings through to record-dispatch"

cat > "$CODEX_SHIM/codex" <<'SH'
#!/usr/bin/env bash
touch "$CODEX_INVOKED"
exit 99
SH
chmod +x "$CODEX_SHIM/codex"
RDLP="$ANGEL_RUNS_ROOT/r_dispatch_leg_preflight"; mkdir -p "$RDLP"
CODEX_INVOKED="$TMP/codex-invoked"
rc=0; dlpout="$(printf 'must not dispatch\n' | CODEX_BIN="$CODEX_SHIM/codex" CODEX_INVOKED="$CODEX_INVOKED" \
  "$DIR/dispatch-leg.sh" --run-dir "$RDLP" --phase persona --name adv --model gpt-5.6-sol \
  --pass 2 --findings 2>&1)" || rc=$?
rc_is $rc 1 "dispatch-leg rejects --findings with --pass 2 during preflight"
[ ! -e "$CODEX_INVOKED" ] && ok "dispatch-leg preflight rejection does not invoke codex" || bad "dispatch-leg preflight rejection does not invoke codex"
has "--findings only composes with --pass 1" "$dlpout" "dispatch-leg preflight rejection explains the invalid composition"

cat > "$CODEX_SHIM/codex" <<'SH'
#!/usr/bin/env bash
cat >/dev/null
printf '%s\n' \
  'OpenAI Codex stub' \
  'model: gpt-5.6-sol' \
  'codex' \
  '#### Important' \
  '- **preserve me** `[trivial]` — `stub.py:2` — record rejection fixture' \
  'tokens used' \
  '234'
SH
chmod +x "$CODEX_SHIM/codex"
RDLR="$ANGEL_RUNS_ROOT/r_dispatch_leg_rejected"; mkdir -p "$RDLR"; printf '2\n' > "$RDLR/MULTIBALL"
rc=0; dlrout="$(printf 'review this prompt\n' | CODEX_BIN="$CODEX_SHIM/codex" "$DIR/dispatch-leg.sh" \
  --run-dir "$RDLR" --phase persona --name adv --model gpt-5.6-sol 2>&1)" || rc=$?
rc_is $rc 1 "dispatch-leg exits nonzero when record-dispatch rejects its output"
rejected_output="$(find "$RDLR/tmp" -maxdepth 1 -type f -name 'rejected-adv-*.out' -print -quit)"
[ -n "$rejected_output" ] && grep -q 'preserve me' "$rejected_output" \
  && ok "dispatch-leg preserves codex output rejected by record-dispatch" || bad "dispatch-leg preserves codex output rejected by record-dispatch"
has "$rejected_output" "$dlrout" "dispatch-leg prints the preserved output path"

cat > "$CODEX_SHIM/codex" <<'SH'
#!/usr/bin/env bash
cat >/dev/null
printf '%s\n' 'partial output before timeout'
exec sleep 5
SH
chmod +x "$CODEX_SHIM/codex"
RDLT="$ANGEL_RUNS_ROOT/r_dispatch_leg_timeout"; mkdir -p "$RDLT"
rc=0; dltout="$(printf 'review this prompt\n' | CODEX_BIN="$CODEX_SHIM/codex" DISPATCH_TIMEOUT_S=0.1 \
  "$DIR/dispatch-leg.sh" --run-dir "$RDLT" --phase persona --name adv --model gpt-5.6-sol --pass 1 2>&1)" || rc=$?
rc_is $rc 1 "dispatch-leg timeout path exits nonzero"
has "timed out after 0.1s" "$dltout" "dispatch-leg timeout path has a distinct error"
has "~/.codex/sessions" "$dltout" "dispatch-leg timeout error names the rollout-recovery path"

cat > "$CODEX_SHIM/codex" <<'SH'
#!/usr/bin/env bash
printf '%s\n' 'garbage output with no final block or meter'
exit 0
SH
chmod +x "$CODEX_SHIM/codex"
RDLF="$ANGEL_RUNS_ROOT/r_dispatch_leg_failed"; mkdir -p "$RDLF"
rc=0; printf 'review this prompt\n' | CODEX_BIN="$CODEX_SHIM/codex" "$DIR/dispatch-leg.sh" \
  --run-dir "$RDLF" --phase persona --name adv --model gpt-5.6-sol --pass 1 \
  >/dev/null 2>&1 || rc=$?
[ "$rc" -ne 0 ] && ok "dispatch-leg garbage-output path exits nonzero" || bad "dispatch-leg garbage-output path exits nonzero"
grep -qE 'angel-pass persona=adv pass=1 model=gpt-5.6-sol( backend=codex)? failed' "$RDLF/passes/adv-p1.md" \
  && ok "dispatch-leg garbage-output path records --failed" || bad "dispatch-leg garbage-output path records --failed"
has '"backend":"codex"' "$(tail -1 "$RDLF/usage.jsonl")" "dispatch-leg failure line retains codex backend"

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
[ ! -e "$RUN_DIR/EXPERIMENT" ] && ok "no EXPERIMENT marker without --experiment" || bad "no EXPERIMENT marker without --experiment"
rc=0; iexp="$(HOME="$TMP/home" "$DIR/init-run.sh" "$SYNTH_PROJ" --experiment "roster swap trial")" || rc=$?
rc_is $rc 0 "init-run --experiment exits 0"
[ "$(printf '%s\n' "$iexp" | wc -l)" -eq 3 ] && ok "--experiment keeps exactly 3 stdout lines (eval contract)" || bad "--experiment keeps exactly 3 stdout lines (eval contract)" "got: $iexp"
RUN_DIR=""; eval "$iexp"; EXP_RUN_DIR="$RUN_DIR"
[ -f "$EXP_RUN_DIR/EXPERIMENT" ] && ok "--experiment writes EXPERIMENT marker" || bad "--experiment writes EXPERIMENT marker"
[ "$(wc -l < "$EXP_RUN_DIR/EXPERIMENT")" -eq 1 ] && ok "EXPERIMENT marker is a single line" || bad "EXPERIMENT marker is a single line"
mline="$(cat "$EXP_RUN_DIR/EXPERIMENT")"
case "$mline" in
  [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z" roster swap trial") ok "marker line is ISO date + reason";;
  *) bad "marker line is ISO date + reason" "got: $mline";;
esac
# f20: PROJECT_DIR with shell metacharacters must be rejected before eval-embedding.
rc=0; HOME="$TMP/home" "$DIR/init-run.sh" '/tmp/project;evil_cmd' 2>/dev/null || rc=$?
rc_is $rc 1 "init-run: semicolon in PROJECT_DIR is rejected"
rc=0; HOME="$TMP/home" "$DIR/init-run.sh" '/tmp/project$(cmd)' 2>/dev/null || rc=$?
rc_is $rc 1 "init-run: dollar-paren in PROJECT_DIR is rejected"
rc=0; HOME="$TMP/home" "$DIR/init-run.sh" '/tmp/project`cmd`' 2>/dev/null || rc=$?
rc_is $rc 1 "init-run: backtick in PROJECT_DIR is rejected"
# A clean path (letters, digits, dots, underscores, hyphens, slashes, spaces) must pass.
rc=0; HOME="$TMP/home" "$DIR/init-run.sh" '/tmp/My Project 1.0/src' 2>/dev/null || rc=$?
rc_is $rc 0 "init-run: path with letters/digits/dots/spaces passes charset check"

# f34: init-run.sh must record PROJECT_COMMIT (short git HEAD or "null") in the run dir.
PROJ_GIT="$TMP/proj_git"; mkdir -p "$PROJ_GIT"
git -C "$PROJ_GIT" init -q
git -C "$PROJ_GIT" config user.email "test@example.com"
git -C "$PROJ_GIT" config user.name "Test"
echo "hello" > "$PROJ_GIT/hello.txt"
git -C "$PROJ_GIT" add hello.txt
git -C "$PROJ_GIT" commit -qm "init"
PROJ_HEAD="$(git -C "$PROJ_GIT" rev-parse --short HEAD)"
F34_RUN_DIR=""
rc=0; eval "$(HOME="$TMP/home" "$DIR/init-run.sh" "$PROJ_GIT")" || rc=$?
F34_RUN_DIR="$RUN_DIR"
rc_is $rc 0 "init-run exits 0 on git project"
[ -f "$F34_RUN_DIR/PROJECT_COMMIT" ] && ok "init-run: PROJECT_COMMIT file written" || bad "init-run: PROJECT_COMMIT file written" "no file at $F34_RUN_DIR/PROJECT_COMMIT"
pcommit="$(cat "$F34_RUN_DIR/PROJECT_COMMIT" 2>/dev/null || echo MISSING)"
[ "$pcommit" = "$PROJ_HEAD" ] && ok "init-run: PROJECT_COMMIT matches git HEAD" || bad "init-run: PROJECT_COMMIT matches git HEAD" "got '$pcommit', expected '$PROJ_HEAD'"
# Non-git project -> PROJECT_COMMIT file contains "null"
PROJ_NOGIT="$TMP/proj_nogit"; mkdir -p "$PROJ_NOGIT"
F34_RUN_DIR2=""
rc=0; eval "$(HOME="$TMP/home" "$DIR/init-run.sh" "$PROJ_NOGIT")" || rc=$?
F34_RUN_DIR2="$RUN_DIR"
rc_is $rc 0 "init-run exits 0 on non-git project"
[ -f "$F34_RUN_DIR2/PROJECT_COMMIT" ] && ok "init-run: PROJECT_COMMIT file written for non-git project" || bad "init-run: PROJECT_COMMIT file written for non-git project"
pcommit2="$(cat "$F34_RUN_DIR2/PROJECT_COMMIT" 2>/dev/null || echo MISSING)"
[ "$pcommit2" = "null" ] && ok "init-run: non-git project writes 'null'" || bad "init-run: non-git project writes 'null'" "got '$pcommit2'"

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
# Mixed-backend entries retain the legacy all-entry total while also exposing
# backend-partitioned measured totals. A missing backend means claude-agent.
RAG_MIX="$ANGEL_RUNS_ROOT/20260601T121000Z-mixed"; mkdir -p "$RAG_MIX/findings"
cat > "$RAG_MIX/usage.jsonl" <<'JSONL'
{"phase":"persona","name":"adv","model":"claude-sonnet-5","total_tokens":10000,"tool_uses":2,"duration_ms":1000,"reader_pack":false}
{"phase":"persona","name":"hyper","model":"gpt-5.6-sol","total_tokens":90000,"tool_uses":null,"duration_ms":2000,"reader_pack":false,"backend":"codex"}
JSONL
rc=0; python3 "$DIR/aggregate-usage.py" "$RAG_MIX" >/dev/null 2>&1 || rc=$?
rc_is $rc 0 "aggregate-usage exits 0 on a mixed-backend fixture"
rc=0; python3 - "$RAG_MIX" <<'PY' || rc=$?
import json, sys
u = json.load(open(sys.argv[1] + "/usage.json"))
assert u["totals"]["total_tokens"] == 100000, u["totals"]
assert u["totals"]["by_backend"] == {"claude-agent": 10000, "codex": 90000}, u["totals"]
personas = {x["name"]: x for x in u["totals"]["personas"]}
assert "backend" not in personas["adv"], personas["adv"]
assert personas["hyper"]["backend"] == "codex", personas["hyper"]
print("mixed-backend-ok")
PY
rc_is $rc 0 "aggregate-usage partitions backend totals and preserves per-entry backend"
# f34: project_commit from PROJECT_COMMIT file must appear in usage.json.
RAG_PC="$ANGEL_RUNS_ROOT/20260601T121500Z-pc1"; mkdir -p "$RAG_PC/findings"; echo "stub" > "$RAG_PC/findings/rtfm.md"
cp "$RAG/usage.jsonl" "$RAG_PC/usage.jsonl"; cp "$RAG/findings-snapshot.json" "$RAG_PC/findings-snapshot.json"
printf 'abc1234\n' > "$RAG_PC/PROJECT_COMMIT"
rc=0; python3 "$DIR/aggregate-usage.py" "$RAG_PC" >/dev/null 2>&1 || rc=$?
rc_is $rc 0 "aggregate-usage exits 0 with PROJECT_COMMIT file"
rc=0; python3 - "$RAG_PC" <<'PY' || rc=$?
import json, sys
u = json.load(open(sys.argv[1] + "/usage.json"))
assert u.get("project_commit") == "abc1234", f"expected 'abc1234', got {u.get('project_commit')}"
print("project-commit-ok")
PY
rc_is $rc 0 "aggregate-usage: project_commit from PROJECT_COMMIT file appears in usage.json"
# Without PROJECT_COMMIT file, project_commit must be null.
RAG_NPC="$ANGEL_RUNS_ROOT/20260601T122000Z-npc1"; mkdir -p "$RAG_NPC/findings"; echo "stub" > "$RAG_NPC/findings/rtfm.md"
cp "$RAG/usage.jsonl" "$RAG_NPC/usage.jsonl"; cp "$RAG/findings-snapshot.json" "$RAG_NPC/findings-snapshot.json"
rc=0; python3 "$DIR/aggregate-usage.py" "$RAG_NPC" >/dev/null 2>&1 || rc=$?
rc=0; python3 - "$RAG_NPC" <<'PY' || rc=$?
import json, sys
u = json.load(open(sys.argv[1] + "/usage.json"))
assert u.get("project_commit") is None, f"expected null without PROJECT_COMMIT file, got {u.get('project_commit')}"
print("no-project-commit-ok")
PY
rc_is $rc 0 "aggregate-usage: project_commit is null without PROJECT_COMMIT file"

echo "== finalize-run.sh =="
rc=0; "$DIR/finalize-run.sh" "$RAG" >/dev/null 2>&1 || rc=$?; rc_is $rc 0 "finalize-run exits 0 on complete fixture"
grep -q "run:$RAG" "$ANGEL_USAGE_LOG" && ok "finalize-run appended usage.log line" || bad "finalize-run appended usage.log line"
rc=0; python3 -c "
import json
d = json.load(open('$RAG/dispositions.json'))
assert sorted(d) == ['f1','f2','f3','f4'], d
assert all(v['disposition'] == 'no-record' for v in d.values()), d
" || rc=$?
rc_is $rc 0 "finalize-run stage 4 emitted dispositions skeleton"
RBAD="$ANGEL_RUNS_ROOT/20260601T130000Z-fixture2"   # no findings-snapshot.json -> completeness gate fails
mkdir -p "$RBAD/findings"; echo "stub" > "$RBAD/findings/rtfm.md"; : > "$RBAD/usage.jsonl"
rc=0; ferr="$("$DIR/finalize-run.sh" "$RBAD" 2>&1 >/dev/null)" || rc=$?
[ "$rc" -ne 0 ] && ok "finalize-run exits nonzero on incomplete fixture" || bad "finalize-run exits nonzero on incomplete fixture"
has "check-run-complete" "$ferr" "finalize-run stderr names the failing stage"

# ADR-12 stage order. The append must come AFTER the gate: appending first allowed
# a gate failure to produce a duplicate log line. A failed run must leave no trace
# in the calibration index.
hasnt "run:$RBAD" "$(cat "$ANGEL_USAGE_LOG")" "gate failure writes NO usage.log line"
has "usage.log line NOT written" "$ferr" "gate failure explains the suppressed append"

# The gate must not require the very line it gates. check-run-complete counts a
# usage.log run: line as a completeness artifact, which is circular once the append moves
# after the gate — --pre-append drops that one requirement and nothing else.
RPA="$ANGEL_RUNS_ROOT/r_preappend"; mkdir -p "$RPA/findings"; mk_snapshot "$RPA"
mk_usage "$RPA" 50000; echo stub > "$RPA/findings/adv.md"
rc=0; python3 "$DIR/check-run-complete.py" --pre-append "$RPA" >/dev/null 2>&1 || rc=$?
rc_is $rc 0 "--pre-append passes a run absent from usage.log"
rc=0; python3 "$DIR/check-run-complete.py" "$RPA" >/dev/null 2>&1 || rc=$?
rc_is $rc 1 "without --pre-append the same run is INCOMPLETE (usage.log line still required)"

# assemble-wpr.py is finalize stage 1 — the producer the provenance gate was always
# enforcing against. It shipped unwired: nothing called it in production for six weeks,
# so the integrator kept hand-writing within_persona_runs and every multiball run failed
# provenance. Pin that finalize actually runs it.
RWP="$ANGEL_RUNS_ROOT/r_wpr_stage1"; mkdir -p "$RWP/findings" "$RWP/passes"; mk_snapshot "$RWP"
mk_usage "$RWP" 50000; echo stub > "$RWP/findings/adv.md"
python3 - "$RWP" <<'PY'
import json, sys
p = sys.argv[1] + "/findings-snapshot.json"
s = json.load(open(p))
s["within_persona_runs"] = {"adv": [[{"severity": "critical", "title": "LLM WROTE THIS", "file": "x.ts", "line": 1}]]}
json.dump(s, open(p, "w"))
PY
"$DIR/finalize-run.sh" "$RWP" >/dev/null 2>&1 || true
rc=0; python3 - "$RWP" <<'PY' || rc=$?
import json, sys
s = json.load(open(sys.argv[1] + "/findings-snapshot.json"))
w = s.get("within_persona_runs")
titles = [f.get("title") for passes in (w or {}).values() for p in passes for f in p]
assert "LLM WROTE THIS" not in titles, f"assemble-wpr did not overwrite the LLM-written field: {w}"
PY
rc_is $rc 0 "finalize stage 1 overwrites an LLM-written within_persona_runs"

echo "== emit-dispositions-skeleton.py =="
SKROOT="$TMP/skelruns"; mkdir -p "$SKROOT"
SK="$SKROOT/r_skel"; mkdir -p "$SK/findings"; mk_snapshot "$SK"
rc=0; sout="$(ANGEL_RUNS_ROOT="$SKROOT" "$DIR/emit-dispositions-skeleton.py" "$SK")" || rc=$?
rc_is $rc 0 "skeleton emit exits 0"
rc=0; python3 - "$SK" <<'PY' || rc=$?
import json, sys
d = json.load(open(sys.argv[1] + "/dispositions.json"))
assert sorted(d) == ["f1", "f2", "f3", "f4"], d
assert all(v == {"disposition": "no-record", "note": "", "recorded_at": None}
           for v in d.values()), d
print("skel-asserts-ok")
PY
rc_is $rc 0 "skeleton has every snapshot id at no-record (record-disposition entry schema)"
hasnt "experiment" "$(cat "$SK/dispositions.json")" "no experiment key without EXPERIMENT marker"
# idempotency: a recorded disposition survives a re-emit byte-for-byte
ANGEL_RUNS_ROOT="$SKROOT" "$DIR/record-disposition.py" "$SK" f1 accepted >/dev/null
cp "$SK/dispositions.json" "$TMP/disp.before"
rc=0; sout2="$(ANGEL_RUNS_ROOT="$SKROOT" "$DIR/emit-dispositions-skeleton.py" "$SK")" || rc=$?
rc_is $rc 0 "re-emit over existing dispositions.json exits 0"
has "already exists" "$sout2" "re-emit reports the no-op"
cmp -s "$TMP/disp.before" "$SK/dispositions.json" && ok "existing dispositions.json untouched (idempotent)" || bad "existing dispositions.json untouched (idempotent)"
rc=0; ANGEL_RUNS_ROOT="$SKROOT" "$DIR/emit-dispositions-skeleton.py" /etc >/dev/null 2>&1 || rc=$?
rc_is $rc 1 "write outside runs-root rejected"
# f26: path-traversal-shaped finding IDs must be skipped with a warning.
SK26="$SKROOT/r_skel_badid"; mkdir -p "$SK26/findings"
cat > "$SK26/findings-snapshot.json" <<'JSON'
{"version":1,"project":"test","mode":"full","verdict":"OK","findings":[
  {"id":"valid-id","severity":"important","title":"Good finding"},
  {"id":"../evil/path","severity":"important","title":"Traversal finding"},
  {"id":"f2; rm -rf /","severity":"minor","title":"Injection finding"}
]}
JSON
rc=0; sk26out="$(ANGEL_RUNS_ROOT="$SKROOT" "$DIR/emit-dispositions-skeleton.py" "$SK26" 2>&1)" || rc=$?
rc_is $rc 0 "emit-dispositions-skeleton: bad finding IDs skipped, exits 0"
has "valid-id" "$(cat "$SK26/dispositions.json" 2>/dev/null)" "valid finding ID written to dispositions"
hasnt "../evil" "$(cat "$SK26/dispositions.json" 2>/dev/null)" "path-traversal ID not written to dispositions"
has "invalid" "$sk26out" "bad finding ID produces a warning in output"
# EXPERIMENT marker -> top-level experiment:true, preserved by record-disposition
SKE="$SKROOT/r_skel_exp"; mkdir -p "$SKE/findings"; mk_snapshot "$SKE"
printf '2026-07-08T00:00:00Z eval leg 2\n' > "$SKE/EXPERIMENT"
ANGEL_RUNS_ROOT="$SKROOT" "$DIR/emit-dispositions-skeleton.py" "$SKE" >/dev/null
rc=0; python3 -c "
import json
d = json.load(open('$SKE/dispositions.json'))
assert d.get('experiment') is True, d
assert d['f1']['disposition'] == 'no-record', d
" || rc=$?
rc_is $rc 0 "EXPERIMENT marker -> top-level experiment:true in skeleton"
ANGEL_RUNS_ROOT="$SKROOT" "$DIR/record-disposition.py" "$SKE" f1 accepted >/dev/null
rc=0; python3 -c "
import json
d = json.load(open('$SKE/dispositions.json'))
assert d.get('experiment') is True, d
assert d['f1']['disposition'] == 'accepted', d
" || rc=$?
rc_is $rc 0 "record-disposition preserves experiment:true on upsert"
rc=0; ANGEL_RUNS_ROOT="$SKROOT" "$DIR/record-disposition.py" "$SKE" experiment accepted 2>/dev/null || rc=$?
rc_is $rc 1 "finding id 'experiment' rejected (reserved marker key)"
# init-run --experiment marker propagates through the skeleton
mk_snapshot "$EXP_RUN_DIR"
"$DIR/emit-dispositions-skeleton.py" "$EXP_RUN_DIR" >/dev/null
rc=0; python3 -c "
import json
d = json.load(open('$EXP_RUN_DIR/dispositions.json'))
assert d.get('experiment') is True, d
" || rc=$?
rc_is $rc 0 "init-run --experiment marker propagates to skeleton experiment:true"
# mine-runs: no-record placeholders are untriaged, not disposed
SKN="$SKROOT/r_skel_untriaged"; mkdir -p "$SKN/findings"; mk_snapshot "$SKN"
ANGEL_RUNS_ROOT="$SKROOT" "$DIR/emit-dispositions-skeleton.py" "$SKN" >/dev/null
mjson2="$("$DIR/mine-runs.py" --runs-dir "$SKROOT" --since 2026-05-31 --json)"
rc=0; python3 - "$mjson2" <<'PY' || rc=$?
import json, sys
d = json.loads(sys.argv[1])
rt = d["personas"]["rtfm"]
assert rt["disposed"] == 2, rt        # f1 accepted in r_skel + r_skel_exp; no-record excluded
assert rt["false_positives"] == 0, rt
assert d["coverage"]["with_dispositions"] == 2, d["coverage"]  # skeleton-only run not counted
print("norecord-asserts-ok")
PY
rc_is $rc 0 "mine-runs: no-record excluded from disposed; skeleton-only run not with-dispositions"

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

echo "== apply-verification.py =="
AV="$ANGEL_RUNS_ROOT/20260601T140000Z-verify1"
mk_usage "$AV" 80000; echo "stub" > "$AV/findings/adv.md"
cat > "$AV/findings-snapshot.json" <<'JSON'
{"version":2,"project":"demo","mode":"full","verdict":"CHANGES REQUIRED",
 "personas_run":["adv","rtfm"],
 "verify_queue":[
  {"id":"f1","severity":"critical","title":"Crit one","file":"src/a.ts","line":"10","claim":"the guard was removed","repro_hint":"check whether the guard path still rejects"},
  {"id":"f2","severity":"important","title":"Imp two","file":"src/b.ts","line":"20","claim":"cap ordering wrong","repro_hint":null}
 ],
 "findings":[
  {"id":"f1","severity":"critical","title":"Crit one","personas":["adv"],"verification":null},
  {"id":"f2","severity":"important","title":"Imp two","personas":["rtfm"],"verification":null},
  {"id":"f3","severity":"minor","title":"Min three","personas":["rtfm"],"verification":null}
 ]}
JSON
printf '# Code Review — CHANGES REQUIRED\n\n## Critical\n\n- stuff\n\n---\n\n*Review by NineAngel — 2026-06-01*\n' > "$AV/report.md"
cp "$AV/findings-snapshot.json" "$TMP/snap.orig"
# path-traversal guard: refuse run dirs outside ANGEL_RUNS_ROOT
rc=0; "$DIR/apply-verification.py" /etc 2>/dev/null || rc=$?; rc_is $rc 1 "write outside runs-root rejected (apply-verification)"
# zero verdict files (missing dir, then empty dir) -> no-op exit 0, nothing written
rc=0; nout="$("$DIR/apply-verification.py" "$AV")" || rc=$?
rc_is $rc 0 "no verification dir -> exit 0"
has "no verdicts to apply" "$nout" "missing-dir no-op message emitted"
mkdir -p "$AV/verification"
rc=0; nout="$("$DIR/apply-verification.py" "$AV")" || rc=$?
rc_is $rc 0 "empty verification dir -> exit 0"
has "no verdicts to apply" "$nout" "empty-dir no-op message emitted"
cmp -s "$TMP/snap.orig" "$AV/findings-snapshot.json" && ok "no-op leaves snapshot untouched" || bad "no-op leaves snapshot untouched"
[ ! -e "$AV/verification-summary.md" ] && ok "no-op writes no summary" || bad "no-op writes no summary"
# happy path: REFUTED + CONFIRMED + unknown-id verdict
cat > "$AV/verification/f1.json" <<'JSON'
{"id":"f1","verdict":"REFUTED","method":"ran","evidence":"repro script shows the guard already covers this","note":"n"}
JSON
cat > "$AV/verification/f2.json" <<'JSON'
{"id":"f2","verdict":"CONFIRMED","method":"traced","evidence":"traced call path to unsanitized sink"}
JSON
cat > "$AV/verification/f9.json" <<'JSON'
{"id":"f9","verdict":"CONFIRMED","method":"ran","evidence":"ghost finding"}
JSON
rc=0; averr="$("$DIR/apply-verification.py" "$AV" 2>&1 >/dev/null)" || rc=$?
rc_is $rc 0 "apply exits 0 despite unknown verdict id"
has "f9" "$averr" "unknown finding id warned to stderr"
rc=0; python3 - "$AV" <<'PY' || rc=$?
import json, sys
s = json.load(open(sys.argv[1] + "/findings-snapshot.json"))
by = {f["id"]: f for f in s["findings"]}
assert by["f1"]["verification"] == {"verdict": "REFUTED", "method": "ran",
    "evidence": "repro script shows the guard already covers this"}, by["f1"]  # note NOT copied
assert by["f2"]["verification"]["verdict"] == "CONFIRMED", by["f2"]
assert by["f3"]["verification"] is None, by["f3"]           # no verdict -> stays null
assert [e["id"] for e in s["verify_queue"]] == ["f1", "f2"], s["verify_queue"] # queue untouched (object schema per integrator.md Phase 3.5)
print("av-asserts-ok")
PY
rc_is $rc 0 "verdicts patched into snapshot; verdict-less finding stays null"

# severity_opinion (2026-08-09): written when the verdict carries it, omitted
# entirely when it does not -- a null on every historical record would make
# "no opinion" and "opinion absent" indistinguishable to mine-runs.py.
rc=0; python3 - "$DIR/apply-verification.py" <<'PY' || rc=$?
import importlib.util, pathlib, sys
script = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("av", script)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
a = [{"id": "f1"}]
m.patch_findings(a, {"f1": {"verdict": "CONFIRMED", "method": "ran", "evidence": "e",
                            "severity_opinion": "too-high"}})
assert a[0]["verification"]["severity_opinion"] == "too-high", a
b = [{"id": "f1"}]
m.patch_findings(b, {"f1": {"verdict": "CONFIRMED", "method": "ran", "evidence": "e"}})
assert "severity_opinion" not in b[0]["verification"], b
print("sev-op-asserts-ok")
PY
rc_is $rc 0 "severity_opinion written when present, omitted when absent"

sm="$(cat "$AV/verification-summary.md")"
has "## Verification" "$sm" "summary has section heading"
has "REFUTED:**" "$sm" "bold warning line above REFUTED items"
has "- **CONFIRMED** f2 (important) — Imp two — traced call path to unsanitized sink" "$sm" "verdict line format: - **verdict** id (severity) — title — evidence"
lr="$(grep -nF '**REFUTED** f1' "$AV/verification-summary.md" | cut -d: -f1)"
lc="$(grep -nF '**CONFIRMED** f2' "$AV/verification-summary.md" | cut -d: -f1)"
[ -n "$lr" ] && [ -n "$lc" ] && [ "$lr" -lt "$lc" ] && ok "REFUTED listed before CONFIRMED" || bad "REFUTED listed before CONFIRMED" "refuted@$lr confirmed@$lc"
has "All verified Criticals were REFUTED" "$sm" "all-criticals-refuted warning fires (only Critical refuted)"
[ "$(grep -c '^## Verification$' "$AV/report.md")" = 1 ] && ok "report.md gained one ## Verification section" || bad "report.md gained one ## Verification section"
has "All verified Criticals were REFUTED" "$(cat "$AV/report.md")" "report section carries the summary content"
# idempotent double-run: snapshot + summary + report all byte-identical
cp "$AV/findings-snapshot.json" "$TMP/snap.after1"; cp "$AV/verification-summary.md" "$TMP/sum.after1"; cp "$AV/report.md" "$TMP/rep.after1"
rc=0; "$DIR/apply-verification.py" "$AV" >/dev/null 2>/dev/null || rc=$?
rc_is $rc 0 "second run exits 0"
cmp -s "$TMP/snap.after1" "$AV/findings-snapshot.json" && ok "snapshot byte-identical after second run" || bad "snapshot byte-identical after second run"
cmp -s "$TMP/sum.after1" "$AV/verification-summary.md" && ok "summary byte-identical after second run" || bad "summary byte-identical after second run"
cmp -s "$TMP/rep.after1" "$AV/report.md" && ok "report.md byte-identical after second run (no duplicate section)" || bad "report.md byte-identical after second run"
# changed verdict -> report section replaced in place, never duplicated
cat > "$AV/verification/f2.json" <<'JSON'
{"id":"f2","verdict":"PLAUSIBLE","method":"traced","evidence":"sink reachable but input already validated upstream"}
JSON
"$DIR/apply-verification.py" "$AV" >/dev/null 2>/dev/null
[ "$(grep -c '^## Verification$' "$AV/report.md")" = 1 ] && ok "re-run replaces report section (still exactly one)" || bad "re-run replaces report section (still exactly one)" "$(grep -c '^## Verification$' "$AV/report.md") sections"
has "PLAUSIBLE" "$(cat "$AV/report.md")" "replaced section carries the new verdict"
hasnt "CONFIRMED" "$(cat "$AV/report.md")" "stale verdict gone from report after replace"
# new schema keys must not break the completeness gate (verification NOT gated in v1)
"$DIR/append-usage-log.sh" "$AV" >/dev/null
rc=0; "$DIR/check-run-complete.py" "$AV" >/dev/null 2>&1 || rc=$?
rc_is $rc 0 "check-run-complete passes with verify_queue/verification keys"
# f26: path-traversal-shaped finding ID in a verdict JSON must be skipped with a warning.
# The ID comes from verdict content (not filename), so write a verdict with a bad id field.
AV_F26="$ANGEL_RUNS_ROOT/20260601T141500Z-f26"; mkdir -p "$AV_F26/verification" "$AV_F26/findings"
echo "stub" > "$AV_F26/findings/adv.md"
cat > "$AV_F26/findings-snapshot.json" <<'JSON'
{"version":2,"project":"f26test","mode":"full","verdict":"OK","personas_run":["adv"],
 "findings":[{"id":"good-id","severity":"important","title":"Good","personas":["adv"],"verification":null}]}
JSON
cat > "$AV_F26/verification/bad.json" <<'JSON'
{"id":"../evil/path","verdict":"CONFIRMED","method":"ran","evidence":"injected"}
JSON
rc=0; avbad_err="$("$DIR/apply-verification.py" "$AV_F26" 2>&1 >/dev/null)" || rc=$?
rc_is $rc 0 "apply-verification: bad finding ID in verdict file is skipped, exits 0"
has "invalid" "$avbad_err" "bad finding ID in verdict produces warning"

# all-criticals-refuted gating: an unverified Critical blocks the warning
AV2="$ANGEL_RUNS_ROOT/20260601T150000Z-verify2"
mkdir -p "$AV2/verification" "$AV2/findings"
cat > "$AV2/findings-snapshot.json" <<'JSON'
{"version":2,"verify_queue":["f1","f2"],"findings":[
 {"id":"f1","severity":"critical","title":"C1","personas":["adv"],"verification":null},
 {"id":"f2","severity":"critical","title":"C2","personas":["adv"],"verification":null}
]}
JSON
cat > "$AV2/verification/f1.json" <<'JSON'
{"id":"f1","verdict":"REFUTED","method":"traced","evidence":"code path not reachable"}
JSON
"$DIR/apply-verification.py" "$AV2" >/dev/null 2>/dev/null
hasnt "All verified Criticals" "$(cat "$AV2/verification-summary.md")" "unverified Critical blocks the all-refuted warning"
cat > "$AV2/verification/f2.json" <<'JSON'
{"id":"f2","verdict":"REFUTED","method":"ran","evidence":"the failing test passes on main"}
JSON
"$DIR/apply-verification.py" "$AV2" >/dev/null 2>/dev/null
has "All verified Criticals were REFUTED" "$(cat "$AV2/verification-summary.md")" "warning fires once every Critical is refuted"

echo "== aggregate-usage.py (verifier phase) =="
RAV="$ANGEL_RUNS_ROOT/20260601T160000Z-verify3"
mkdir -p "$RAV/findings"; echo "stub" > "$RAV/findings/adv.md"
cat > "$RAV/usage.jsonl" <<'JSONL'
{"phase":"persona","name":"adv","model":"claude-sonnet-4-6","total_tokens":50000,"tool_uses":10,"duration_ms":60000,"started_at":"2026-06-01T16:05:00Z","ended_at":"2026-06-01T16:06:00Z","reader_pack":false}
{"phase":"verifier","name":"f1","model":"claude-sonnet-4-6","total_tokens":7000,"tool_uses":3,"duration_ms":30000,"started_at":null,"ended_at":null,"reader_pack":false}
{"phase":"verifier","name":"f2","model":"claude-sonnet-4-6","total_tokens":null,"tool_uses":null,"duration_ms":null,"started_at":null,"ended_at":null,"reader_pack":false,"note":"unmeasured"}
JSONL
rc=0; python3 "$DIR/aggregate-usage.py" "$RAV" >/dev/null 2>&1 || rc=$?
rc_is $rc 0 "aggregate-usage exits 0 with verifier-phase lines"
rc=0; python3 - "$RAV" <<'PY' || rc=$?
import json, sys
u = json.load(open(sys.argv[1] + "/usage.json"))
assert u["totals"]["total_tokens"] == 57000, u["totals"]["total_tokens"]  # verifier tokens counted
assert u["unmeasured"] == ["verifier:f2"], u["unmeasured"]                # null verifier surfaces
assert len(u["totals"]["personas"]) == 1, u["totals"]["personas"]         # not misfiled as personas
assert u["totals"]["integrator"] is None, u["totals"]["integrator"]      # nor as integrator
print("rav-asserts-ok")
PY
rc_is $rc 0 "verifier lines aggregate into totals; not misfiled per-phase"

# f22: aggregate-usage must pick the LAST non-stalled integrator entry, not the first.
RSTALL="$ANGEL_RUNS_ROOT/20260601T165000Z-stall1"
mkdir -p "$RSTALL/findings"; echo "stub" > "$RSTALL/findings/adv.md"
cat > "$RSTALL/usage.jsonl" <<'JSONL'
{"phase":"persona","name":"adv","model":"claude-sonnet-4-6","total_tokens":40000,"tool_uses":8,"duration_ms":50000,"started_at":"2026-06-01T16:50:00Z","ended_at":"2026-06-01T16:51:00Z","reader_pack":false}
{"phase":"integrator","name":"integrator","model":"claude-fable-5[1m]","total_tokens":null,"tool_uses":null,"duration_ms":null,"started_at":null,"ended_at":null,"reader_pack":false,"note":"STALLED"}
{"phase":"integrator","name":"integrator","model":"claude-opus-4-8[1m]","total_tokens":18000,"tool_uses":0,"duration_ms":90000,"started_at":"2026-06-01T17:10:00Z","ended_at":"2026-06-01T17:12:00Z","reader_pack":false}
JSONL
rc=0; python3 "$DIR/aggregate-usage.py" "$RSTALL" >/dev/null 2>&1 || rc=$?
rc_is $rc 0 "aggregate-usage exits 0 with stalled+delivered integrator pair"
rc=0; python3 - "$RSTALL" <<'PY' || rc=$?
import json, sys
u = json.load(open(sys.argv[1] + "/usage.json"))
# The delivered (Opus) entry, not the stalled (Fable) entry, must be recorded.
assert u["totals"]["integrator"]["model"] == "claude-opus-4-8[1m]", \
    f"expected Opus (delivered) integrator, got {u['totals']['integrator']}"
assert u["totals"]["integrator"]["total_tokens"] == 18000, \
    f"expected 18000 tokens from delivered entry, got {u['totals']['integrator']}"
print("stall-integrator-ok")
PY
rc_is $rc 0 "aggregate-usage: stalled+delivered pair attributes Opus (delivered), not Fable (stalled)"

# f21: reconciler + verifier phase buckets must appear in totals as arrays.
RRC="$ANGEL_RUNS_ROOT/20260601T170000Z-recon1"
mkdir -p "$RRC/findings"; echo "stub" > "$RRC/findings/adv.md"
cat > "$RRC/usage.jsonl" <<'JSONL'
{"phase":"persona","name":"adv","model":"claude-sonnet-4-6","total_tokens":40000,"tool_uses":8,"duration_ms":50000,"started_at":"2026-06-01T17:05:00Z","ended_at":"2026-06-01T17:06:00Z","reader_pack":false}
{"phase":"reconciler","name":"reconciler-1","model":"claude-haiku-4-5","total_tokens":5000,"tool_uses":2,"duration_ms":10000,"started_at":null,"ended_at":null,"reader_pack":false}
{"phase":"reconciler","name":"reconciler-2","model":"claude-haiku-4-5","total_tokens":6000,"tool_uses":2,"duration_ms":12000,"started_at":null,"ended_at":null,"reader_pack":false}
{"phase":"verifier","name":"f3","model":"claude-sonnet-4-6","total_tokens":8000,"tool_uses":3,"duration_ms":30000,"started_at":null,"ended_at":null,"reader_pack":false}
JSONL
rc=0; python3 "$DIR/aggregate-usage.py" "$RRC" >/dev/null 2>&1 || rc=$?
rc_is $rc 0 "aggregate-usage exits 0 with reconciler+verifier lines"
rc=0; python3 - "$RRC" <<'PY' || rc=$?
import json, sys
u = json.load(open(sys.argv[1] + "/usage.json"))
# Total includes all phases
assert u["totals"]["total_tokens"] == 59000, u["totals"]["total_tokens"]
# reconcilers array present with 2 entries
assert "reconcilers" in u["totals"], "reconcilers bucket missing from totals"
assert len(u["totals"]["reconcilers"]) == 2, u["totals"]["reconcilers"]
assert u["totals"]["reconcilers"][0]["name"] == "reconciler-1", u["totals"]["reconcilers"][0]
assert u["totals"]["reconcilers"][1]["total_tokens"] == 6000, u["totals"]["reconcilers"][1]
# verifiers array present with 1 entry
assert "verifiers" in u["totals"], "verifiers bucket missing from totals"
assert len(u["totals"]["verifiers"]) == 1, u["totals"]["verifiers"]
assert u["totals"]["verifiers"][0]["name"] == "f3", u["totals"]["verifiers"][0]
# personas array has only the persona entry (not contaminated by reconcilers/verifiers)
assert len(u["totals"]["personas"]) == 1, u["totals"]["personas"]
assert u["totals"]["personas"][0]["name"] == "adv", u["totals"]["personas"][0]
print("reconciler-verifier-bucket-ok")
PY
rc_is $rc 0 "reconciler/verifier phase buckets appear in totals as separate arrays"

echo
echo "--- subsample-analyzer + shared matcher suite (test_subsample.py) ---"
rc=0; python3 "$DIR/test_subsample.py" || rc=$?
rc_is $rc 0 "subsample-analyzer + finding_match suite passes"

echo
echo "--- cross-persona overlap suite (test_persona_overlap.py) ---"
rc=0; python3 "$DIR/test_persona_overlap.py" || rc=$?
rc_is $rc 0 "persona-overlap suite passes"

echo
echo "--- md->struct parser suite (test_parse_findings.py) ---"
rc=0; python3 "$DIR/test_parse_findings.py" || rc=$?
rc_is $rc 0 "parse-findings suite passes"

echo
echo "--- mine-runs fp accounting suite (test_mine_runs_fp.py) ---"
rc=0; python3 "$DIR/test_mine_runs_fp.py" || rc=$?
rc_is $rc 0 "mine-runs fp suite passes"

echo
echo "--- within_persona_runs assembler suite (test_assemble_wpr.py) ---"
rc=0; python3 "$DIR/test_assemble_wpr.py" || rc=$?
rc_is $rc 0 "assemble-wpr suite passes"

echo
echo "--- ADR/SKILL.md consistency gate (test_adr_consistency.py) ---"
rc=0; python3 "$DIR/test_adr_consistency.py" || rc=$?
rc_is $rc 0 "adr-consistency suite passes"

echo
echo "--- codex leg dispatcher suite (test_dispatch_leg.sh) ---"
rc=0; bash "$DIR/test_dispatch_leg.sh" || rc=$?
rc_is $rc 0 "dispatch-leg suite passes"

echo
echo "--- true-cost per-request collapse suite (test_true_cost.py) ---"
rc=0; python3 "$DIR/test_true_cost.py" || rc=$?
rc_is $rc 0 "true-cost suite passes"

echo
echo "--- ADR-16 falsifier instrument suite (test_pass_support_accuracy.py) ---"
rc=0; python3 "$DIR/test_pass_support_accuracy.py" || rc=$?
rc_is $rc 0 "pass-support-accuracy suite passes"

echo
echo "--- ADR-19 falsifier instrument suite (test_depth_lane_yield.py) ---"
rc=0; python3 "$DIR/test_depth_lane_yield.py" || rc=$?
rc_is $rc 0 "depth-lane-yield suite passes"

echo
echo "--- ADR-20 bounded integration workset suite ---"
rc=0; python3 "$DIR/test_integration_workset.py" || rc=$?
rc_is $rc 0 "bounded integration workset suite passes"

echo
echo "--- ADR-20 deterministic renderer suite ---"
rc=0; python3 "$DIR/test_render_integration.py" || rc=$?
rc_is $rc 0 "deterministic renderer suite passes"

echo
echo "--- ADR-20 subscription reducer boundary suite ---"
rc=0; python3 "$DIR/test_reducer_sandbox.py" || rc=$?
rc_is $rc 0 "subscription reducer boundary suite passes"

echo
echo "--- ADR-20 composed integration pipeline suite ---"
rc=0; python3 "$DIR/test_integration_pipeline.py" || rc=$?
rc_is $rc 0 "composed integration pipeline suite passes"

echo
echo "--- ADR-22 Jev reconciliation shadow suite ---"
rc=0; python3 "$DIR/test_jev_reconciliation.py" || rc=$?
rc_is $rc 0 "Jev reconciliation shadow suite passes"

echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
