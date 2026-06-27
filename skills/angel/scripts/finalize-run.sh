#!/usr/bin/env bash
# pattern: imperative shell
# One mechanical end-of-run gate — SKILL.md §8a-c in a single call, so a run
# record cannot be left half-written by orchestrator drift (ADR-03 reboot
# condition 4: run-record completeness enforced, not disciplined). Runs:
#   1. aggregate-usage.py     usage.jsonl -> usage.json (§8a)
#   2. append-usage-log.sh    canonical usage.log line   (§8b)
#   3. check-run-complete.py  completeness gate          (§8c)
# Stops at the first failure, naming the failing stage on stderr.
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

stage "aggregate-usage.py" python3 "$SCRIPT_DIR/aggregate-usage.py" "$RUN_DIR"
if [[ -n "$RUN_TAG" ]]; then
  stage "append-usage-log.sh" "$SCRIPT_DIR/append-usage-log.sh" "$RUN_DIR" "$RUN_TAG"
else
  stage "append-usage-log.sh" "$SCRIPT_DIR/append-usage-log.sh" "$RUN_DIR"
fi
stage "check-run-complete.py" python3 "$SCRIPT_DIR/check-run-complete.py" "$RUN_DIR"
