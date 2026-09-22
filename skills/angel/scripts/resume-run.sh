#!/usr/bin/env bash
# pattern: imperative shell
# Diagnostic helper: given an existing $RUN_DIR, report which artifacts exist
# and which phase the run reached, so a human (or orchestrator) can decide
# where to re-enter an interrupted run.
#
# Usage: resume-run.sh <run_dir>
# Exit 0: run is complete (all expected artifacts present).
# Exit 1: run is incomplete — prints the first missing phase and what exists.
#
# This script is READ-ONLY and DIAGNOSTIC. It does not dispatch, modify, or
# delete anything. It does not know how to re-run — that is the orchestrator's
# job once it reads this output.
#
# Artifacts checked (in phase order):
#   findings/*.md         — persona outputs (Phase 1/2: persona dispatch)
#   passes/*-p*.md        — per-pass files for multiball (Phase 2: passes complete)
#   reconciled/*.md       — Stage-1 reconciler outputs (Phase 3: reconcilers complete)
#   findings-snapshot.json — integrator output (Phase 4: integrator complete)
#   usage.json            — aggregated usage (Phase 5: finalize-run.sh ran)
#   report.md             — final report (Phase 4: integrator wrote it)
#
# "Resuming an interrupted run" — see SKILL.md §8 or §5.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="${1:-}"

if [ -z "$RUN_DIR" ]; then
  echo "usage: resume-run.sh <run_dir>" >&2
  exit 1
fi

if [ ! -d "$RUN_DIR" ]; then
  echo "error: run dir not found: $RUN_DIR" >&2
  exit 1
fi

RD="$(realpath "$RUN_DIR")"
echo "Run dir: $RD"
echo ""

# --- Check each phase ---
PHASE="unknown"
MISSING=""

# Phase 1: persona findings
FINDINGS_COUNT=0
if [ -d "$RD/findings" ]; then
  FINDINGS_COUNT=$(find "$RD/findings" -name "*.md" | wc -l | tr -d ' ')
fi
if [ "$FINDINGS_COUNT" -eq 0 ]; then
  MISSING="findings/*.md (no persona outputs)"
  PHASE="persona dispatch (never started or all failed)"
else
  echo "findings/     : $FINDINGS_COUNT file(s) — persona dispatch ran"
  PHASE="after persona dispatch"
fi

# Phase 2: multiball passes
PASS_COUNT=0
if [ -d "$RD/passes" ]; then
  PASS_COUNT=$(find "$RD/passes" -name "*-p*.md" | wc -l | tr -d ' ')
fi
MULTIBALL_N=0
if [ -f "$RD/MULTIBALL" ]; then
  MULTIBALL_N=$(cat "$RD/MULTIBALL" 2>/dev/null || echo 0)
fi
if [ "$MULTIBALL_N" -ge 2 ] || [ "$PASS_COUNT" -gt 0 ]; then
  echo "MULTIBALL     : N=$MULTIBALL_N marker; $PASS_COUNT pass file(s) in passes/"
  if [ "$PASS_COUNT" -eq 0 ] && [ -z "$MISSING" ]; then
    MISSING="passes/*-p*.md (multiball passes not written)"
    PHASE="after multiball pass dispatch started (passes missing)"
  fi
fi

# Phase 3: reconcilers
RECON_COUNT=0
if [ -d "$RD/reconciled" ]; then
  RECON_COUNT=$(find "$RD/reconciled" -name "*.md" | wc -l | tr -d ' ')
fi
if [ "$RECON_COUNT" -gt 0 ]; then
  echo "reconciled/   : $RECON_COUNT file(s) — Stage-1 reconcilers ran"
  PHASE="after Stage-1 reconcilers"
elif [ "$MULTIBALL_N" -ge 2 ] && [ "$PASS_COUNT" -gt 0 ] && [ -z "$MISSING" ]; then
  MISSING="reconciled/*.md (Stage-1 reconcilers have not run)"
  PHASE="after passes; reconcilers pending"
fi

# Phase 4: integrator outputs
HAS_SNAPSHOT=false; HAS_REPORT=false
[ -f "$RD/findings-snapshot.json" ] && HAS_SNAPSHOT=true
[ -f "$RD/report.md" ] && HAS_REPORT=true
if $HAS_SNAPSHOT && $HAS_REPORT; then
  echo "integrator    : findings-snapshot.json + report.md present"
  PHASE="after integrator"
elif [ -z "$MISSING" ]; then
  [ ! -f "$RD/findings-snapshot.json" ] && MISSING="findings-snapshot.json (integrator did not complete)"
  [ ! -f "$RD/report.md" ] && MISSING="${MISSING:+$MISSING, }report.md (integrator did not complete)"
  PHASE="integrator incomplete or not started"
fi

# Phase 5: finalize
HAS_USAGE=false
[ -f "$RD/usage.json" ] && HAS_USAGE=true
if $HAS_USAGE; then
  echo "usage.json    : present — finalize-run.sh ran"
  PHASE="complete (finalize-run.sh ran)"
elif [ -z "$MISSING" ]; then
  MISSING="usage.json (finalize-run.sh has not run)"
  PHASE="integrator complete; finalize pending"
fi

echo ""
echo "Phase reached : $PHASE"

if [ -n "$MISSING" ]; then
  echo "First missing : $MISSING"
  echo ""
  echo "Re-entry point: $DIR/integrate-run.sh '$RD' --resume"
  exit 1
fi

echo "Status        : COMPLETE"
exit 0
