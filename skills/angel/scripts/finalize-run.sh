#!/usr/bin/env bash
# pattern: imperative shell
# One mechanical end-of-run gate — SKILL.md §8a-c in a single call, so a run
# record cannot be left half-written by orchestrator drift (ADR-03 reboot
# condition 4: run-record completeness enforced, not disciplined).
#
# Stage order is ADR-12's edit map, and the order is load-bearing:
#   1. assemble-wpr.py             passes/*.md -> within_persona_runs (SCRIPT, not LLM)
#   2. aggregate-usage.py          usage.jsonl -> usage.json (§8a; reads counts, must follow 1)
#   3. check-run-complete.py       completeness + provenance GATE (§8c)
#   4. append-usage-log.sh         canonical usage.log line (§8b) — ONLY IF THE GATE PASSED
#   5. emit-dispositions-skeleton  dispositions.json skeleton — every finding starts
#                                  "no-record", so non-triage is recorded, not inferred
#
# Why 4 is after 3: appending before the gate lets a failed then remediated
# finalization create contradictory duplicate index entries. Do not move the
# append above the gate.
#
# Why 1 exists at all: provenance checking requires a deterministic producer.
# Stage 1 creates within_persona_runs before the gate compares the stored value
# with its recomputation.
#
# Gate-fail is alert + NO append (an incomplete run must not enter the calibration index;
# the run dir on disk plus this alert are the recovery path — see resume-run.sh).
#
# Usage: finalize-run.sh <RUN_DIR> [RUN_TAG]
set -euo pipefail

RUN_DIR="${1:?usage: finalize-run.sh <RUN_DIR> [RUN_TAG]}"
RUN_TAG="${2:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

stage() { # $1=stage name, rest=command
  local name="$1"; shift
  if ! "$@"; then
    echo "finalize-run: stage failed: $name" >&2
    exit 1
  fi
}

REDUCER_ERA="$(python3 - "$RUN_DIR" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1])/'findings-snapshot.json'
try: print('yes' if json.loads(p.read_text()).get('version') == 3 else 'no')
except Exception: print('no')
PY
)"
if [[ "$REDUCER_ERA" == yes ]]; then
  stage "validate-integration-decisions.py" python3 "$SCRIPT_DIR/validate-integration-decisions.py" \
    "$RUN_DIR/integration-workset.json" "$RUN_DIR/integration-decisions.json"
fi

stage "assemble-wpr.py" python3 "$SCRIPT_DIR/assemble-wpr.py" "$RUN_DIR"
stage "aggregate-usage.py" python3 "$SCRIPT_DIR/aggregate-usage.py" "$RUN_DIR"

# The gate. On failure: alert loudly, do NOT append, exit nonzero.
if ! python3 "$SCRIPT_DIR/check-run-complete.py" --pre-append "$RUN_DIR"; then
  cat >&2 <<EOF
finalize-run: stage failed: check-run-complete.py
finalize-run: run is INCOMPLETE — usage.log line NOT written (ADR-12).
finalize-run:   run dir: $RUN_DIR
finalize-run:   Fix the missing artifacts and re-run finalize-run.sh; the append is
finalize-run:   idempotent on the run: pointer, so re-finalizing corrects the record
finalize-run:   rather than duplicating it. See scripts/resume-run.sh for the phase map.
EOF
  exit 1
fi

if [[ -n "$RUN_TAG" ]]; then
  stage "append-usage-log.sh" "$SCRIPT_DIR/append-usage-log.sh" "$RUN_DIR" "$RUN_TAG"
else
  stage "append-usage-log.sh" "$SCRIPT_DIR/append-usage-log.sh" "$RUN_DIR"
fi
stage "emit-dispositions-skeleton.py" python3 "$SCRIPT_DIR/emit-dispositions-skeleton.py" "$RUN_DIR"
