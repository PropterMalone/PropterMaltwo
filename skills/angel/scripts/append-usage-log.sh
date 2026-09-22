#!/usr/bin/env bash
# pattern: imperative shell
# Append one canonical line to usage.log, generated from a run's usage.json.
#
# The line format lives HERE, once. The /angel orchestrator MUST call this and
# never hand-format the usage.log line: hand-formatting can produce field drift
# (tok:/tokens:/total_tokens:) and drop the run: pointer. usage.json (the per-Agent meter,
# SKILL.md §8a) is the source of truth for cost — not the integrator snapshot's
# resource_consumption, which is the unreliable path the meter replaced.
#
# Usage: append-usage-log.sh <RUN_DIR> [CAL_TAG]
#   CAL_TAG: optional §1.6 calibration tag (e.g. baseline / reader) -> appends cal:<tag>
set -euo pipefail

RUN_DIR="${1:?usage: append-usage-log.sh <RUN_DIR> [CAL_TAG]}"
CAL_TAG="${2:-}"
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="${ANGEL_USAGE_LOG:-$SKILL_DIR/usage.log}"   # override for tests
USAGE_JSON="$RUN_DIR/usage.json"
TODAY="$(date +%F)"

# Idempotent on the run: pointer — a run appears in usage.log at most once.
#
# finalize-run.sh appends BEFORE check-run-complete.py runs, so an orchestrator that
# re-finalizes (after the completeness gate fails, or because the interactive and
# unattended paths both fire) wrote a second line for the same run. Observed
# 2026-08-02: run SYNTHETIC-DUPE-A logged twice with CONTRADICTORY counts —
# 0C/0I/0M/0N from a premature finalize, then 2C/10I/5M/0N once findings landed. Any
# cross-run miner reading precision off this log was reading corrupted input.
#
# Later write wins: the re-finalize is the more complete record. The supersede is
# announced on stderr rather than done silently — the double-call is still a caller
# bug, and hiding it here would just move the defect somewhere harder to see.
emit() {
  local line="$1" key="run:$RUN_DIR" tmp
  if [[ -f "$LOG" ]] && grep -qF -- "$key" "$LOG" 2>/dev/null; then
    tmp="$(mktemp "${LOG}.XXXXXX")"
    if awk -v key="$key" '
        { i = index($0, key)
          if (i > 0) {
            nxt = substr($0, i + length(key), 1)
            if (nxt == "" || nxt == " ") next    # supersede: drop the earlier line
          }
          print }
      ' "$LOG" > "$tmp"; then
      mv -f "$tmp" "$LOG"
      echo "note: superseded an existing usage.log line for $RUN_DIR (re-finalize)" >&2
    else
      rm -f "$tmp"
      echo "warning: could not rewrite $LOG; appending without supersede" >&2
    fi
  fi
  printf '%s\n' "$line" >> "$LOG"
  printf '%s\n' "$line"
}

if [[ ! -f "$USAGE_JSON" ]]; then
  emit "$TODAY | UNKNOWN | ? | ? | ? | ?C/?I/?M/?N | note:usage.json-missing run:$RUN_DIR${CAL_TAG:+ cal:$CAL_TAG}"
  echo "warning: $USAGE_JSON missing; wrote fallback line" >&2
  exit 0
fi

if ! line="$(jq -er --arg rundir "$RUN_DIR" --arg today "$TODAY" --arg cal "$CAL_TAG" '
  def s(x): (x // 0);
  def clean(x): (x | tostring | gsub("[|\n]"; " "));   # | is the field delimiter; strip it from every free-text field
  ( if (.started_at // "") == "" then $today else (.started_at | split("T")[0]) end ) as $date
  | [ .totals.personas[]?.name | clean(.) ] as $pn
  | [ $date,
      clean(.project // "UNKNOWN"),
      clean(.mode // "?"),
      "\($pn|length) (\($pn|join(",")))",
      clean(.verdict // "?"),
      "\(s(.findings.critical))C/\(s(.findings.important))I/\(s(.findings.minor))M/\(s(.findings.noted))N",
      ( (if .totals.total_tokens == null then "total:null" else "total:\(.totals.total_tokens)" end)
        + " wall:\(s(.totals.wall_seconds))s reader:\(if .reader_enabled then "on" else "off" end)"
        + (if .totals.reader then " reader_total:\(if .totals.reader.total_tokens == null then "null" else "\(.totals.reader.total_tokens)" end) reader_wall:\((s(.totals.reader.duration_ms)/1000)|floor)s" else "" end)
        + (if ((.unmeasured // []) | length) > 0 then " unmeasured:\((.unmeasured|length))" else "" end)
        + (if .scale then
             (if .scale.files then " files:\(.scale.files)" else "" end)
             + (if .scale.diff_lines then " difflines:\(.scale.diff_lines)" else "" end)
           else "" end)
        + " run:\(.run_dir // $rundir)"
        + (if $cal != "" then " cal:\($cal)" else "" end) )
    ] | join(" | ")
' "$USAGE_JSON" 2>/dev/null)"; then
  emit "$TODAY | UNKNOWN | ? | ? | ? | ?C/?I/?M/?N | note:usage.json-malformed run:$RUN_DIR${CAL_TAG:+ cal:$CAL_TAG}"
  echo "warning: $USAGE_JSON malformed; wrote fallback line" >&2
  exit 0
fi

emit "$line"
