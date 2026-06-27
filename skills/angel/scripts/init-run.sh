#!/usr/bin/env bash
# pattern: imperative shell
# Mechanizes SKILL.md §3.4 run setup — the authoritative creator of the run
# substrate (RUN_DIR/findings/, empty usage.jsonl, HANDOFF_DIR). Hand-building
# these paths in the orchestrator is the LLM-discipline failure ADR-03 reboot
# condition 4 closes: stdout is exactly three eval-able assignments, so the
# orchestrator does `eval "$(init-run.sh [PROJECT_DIR])"` and cannot drift.
#
# Usage: eval "$(init-run.sh [PROJECT_DIR])"   # PROJECT_DIR defaults to $(pwd)
set -euo pipefail

RUNS_ROOT="${ANGEL_RUNS_ROOT:-$HOME/.angel/runs}"   # override for tests
RUN_DIR="$RUNS_ROOT/$(date -u +%Y%m%dT%H%M%SZ)-$(uuidgen 2>/dev/null | cut -c1-8 || echo "$$")"
mkdir -p "$RUN_DIR/findings"
: > "$RUN_DIR/usage.jsonl"

PROJECT_DIR="${1:-$(pwd)}"
# slash→dash encoding kept deliberately: it mirrors Claude Code's own
# per-project memory-dir convention; changing it would orphan every existing
# memory dir. Known limits: distinct paths can collide (/a/b vs /a-b), and
# shell metacharacters are unsupported — keep project paths to [A-Za-z0-9._/-].
ENCODED_CWD="${PROJECT_DIR//\//-}"
HANDOFF_DIR="$HOME/.claude/projects/$ENCODED_CWD/memory"
mkdir -p "$HANDOFF_DIR"

printf "RUN_DIR='%s'\n" "$RUN_DIR"
printf "ENCODED_CWD='%s'\n" "$ENCODED_CWD"
printf "HANDOFF_DIR='%s'\n" "$HANDOFF_DIR"
