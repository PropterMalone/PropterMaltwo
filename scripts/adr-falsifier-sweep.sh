#!/usr/bin/env bash
# Cron entry point for the mechanical ADR falsifier sweep.
#
# Thin on purpose: flock for single-instance, an absolute interpreter because
# cron's PATH is not a login shell's, and nothing else. All logic lives in
# adr-sweep.py, which always exits 0 on a completed run.
#
# Install (weekly, Monday morning):
#   17 6 * * 1 $HOME/.claude/scripts/adr-falsifier-sweep.sh
#
# This script NEVER runs git. Committing sweep writes was rejected: an
# unattended committer across every project repo risks wrong-branch and
# wrong-identity commits and index collisions with live sessions. An
# uncommitted line a destructive git op wipes self-heals at the next sweep,
# and the log holds the history.
#
# Usage: adr-falsifier-sweep.sh [--dry-run] [--no-tasks] [--no-notify] [--only SUBSTR] [--json]
set -uo pipefail   # deliberately NOT -e: a failed flock must not look like a crash

CLAUDE_DIR="${ADR_SWEEP_CLAUDE_DIR:-$HOME/.claude}"
STATE_DIR="${ADR_SWEEP_STATE:-$CLAUDE_DIR/state}"
# adapt: absolute, because a cron shell may not have python3 on PATH. `command -v
# python3` in your login shell prints the right value for your machine.
PYTHON="${ADR_SWEEP_PYTHON:-/usr/bin/python3}"

mkdir -p "$STATE_DIR" 2>/dev/null || true
exec flock -n "$STATE_DIR/adr-sweep.lock" "$PYTHON" "$CLAUDE_DIR/scripts/adr-sweep.py" "$@"
