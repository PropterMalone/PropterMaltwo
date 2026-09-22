#!/usr/bin/env bash
# pattern: imperative shell
# Mechanizes SKILL.md §3.4 run setup — the authoritative creator of the run
# substrate (RUN_DIR/findings/, empty usage.jsonl, HANDOFF_DIR). Hand-building
# these paths in the orchestrator is the LLM-discipline failure ADR-03 reboot
# condition 4 closes: stdout is exactly three eval-able assignments, so the
# orchestrator does `eval "$(init-run.sh [PROJECT_DIR])"` and cannot drift.
#
# Usage: eval "$(init-run.sh [PROJECT_DIR] [--experiment [REASON]])"
#   PROJECT_DIR defaults to $(pwd). --experiment writes an EXPERIMENT marker
#   file (ISO date + optional reason) into the run dir, so finalize-run's
#   dispositions skeleton tags the run experiment:true — untriaged findings
#   from experiment runs stay distinguishable from neglected live ones.
set -euo pipefail

EXPERIMENT=0; EXPERIMENT_REASON=""; POSITIONAL=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --experiment)
      EXPERIMENT=1; shift
      # optional reason: consume the next arg unless it's another flag —
      # so pass PROJECT_DIR before --experiment, not after.
      if [[ $# -gt 0 && "$1" != --* ]]; then EXPERIMENT_REASON="$1"; shift; fi
      ;;
    *) POSITIONAL+=("$1"); shift ;;
  esac
done

RUNS_ROOT="${ANGEL_RUNS_ROOT:-$HOME/.angel/runs}"   # override for tests
RUN_DIR="$RUNS_ROOT/$(date -u +%Y%m%dT%H%M%SZ)-$(uuidgen 2>/dev/null | cut -c1-8 || echo "$$")"
mkdir -p "$RUN_DIR/findings"
: > "$RUN_DIR/usage.jsonl"
if [[ "$EXPERIMENT" -eq 1 ]]; then
  if [[ -n "$EXPERIMENT_REASON" ]]; then
    printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$EXPERIMENT_REASON" > "$RUN_DIR/EXPERIMENT"
  else
    printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$RUN_DIR/EXPERIMENT"
  fi
fi

PROJECT_DIR="${POSITIONAL[0]:-$(pwd)}"
# Validate PROJECT_DIR before embedding it in the eval-able stdout block.
# Supported charset: letters, digits, dots, underscores, hyphens, slashes, spaces.
# (Same as the documented constraint in the script header.) Any other character —
# semicolons, backticks, $(...), etc. — can break the eval and cause injection.
if [[ -n "$PROJECT_DIR" ]] && ! [[ "$PROJECT_DIR" =~ ^[A-Za-z0-9._/\ -]+$ ]]; then
  printf 'init-run.sh: PROJECT_DIR contains unsupported characters (allowed: A-Za-z0-9._/- and space): %s\n' "$PROJECT_DIR" >&2
  exit 1
fi
# slash→dash encoding kept deliberately: it mirrors Claude Code's own
# per-project memory-dir convention; changing it would orphan every existing
# memory dir. Known limits: distinct paths can collide (/a/b vs /a-b), and
# shell metacharacters are unsupported — keep project paths to [A-Za-z0-9._/- ].
ENCODED_CWD="${PROJECT_DIR//\//-}"
HANDOFF_DIR="$HOME/.claude/projects/$ENCODED_CWD/memory"
mkdir -p "$HANDOFF_DIR"

# Record the reviewed project's git HEAD (short SHA) for provenance. A non-git
# project (or git unavailable) writes "null" so aggregate-usage.py can distinguish
# "checked and absent" from "never checked" (f34).
PROJECT_COMMIT="$(git -C "$PROJECT_DIR" rev-parse --short HEAD 2>/dev/null || echo null)"
printf '%s\n' "$PROJECT_COMMIT" > "$RUN_DIR/PROJECT_COMMIT"

# ADR-20: create the durable metadata channel before any semantic integration.
# Fields that are only known after pre-flight/selection are explicitly null/empty and
# atomically completed by record-run-meta.py; the builder rejects an incomplete file.
python3 - "$RUN_DIR/run-meta.json" "$PROJECT_DIR" <<'PY'
import datetime, json, os, sys, tempfile
path, project_dir = sys.argv[1:]
body = {
    "version": 1,
    "integration_pipeline": "semantic-reducer-v1",
    "status": "building",
    "run_dir": os.path.dirname(path),
    "project_dir": os.path.abspath(project_dir),
    "project": os.path.basename(os.path.abspath(project_dir)) or "unknown",
    "date": datetime.datetime.now(datetime.timezone.utc).date().isoformat(),
    "mode": None,
    "reader_mode": None,
    "files_reviewed": None,
    "preflight": None,
    "multiball": None,
    "pass_denominators": {},
    "personas_run": [],
    "personas_dropped": [],
    "personas_failed": [],
    "codebase": {"files": None, "lines": None},
    "previous_run_dir": None,
}
fd, tmp = tempfile.mkstemp(prefix=".run-meta.", dir=os.path.dirname(path), text=True)
with os.fdopen(fd, "w", encoding="utf-8") as f:
    json.dump(body, f, indent=2, ensure_ascii=False); f.write("\n")
os.replace(tmp, path)
PY

printf "RUN_DIR='%s'\n" "$RUN_DIR"
printf "ENCODED_CWD='%s'\n" "$ENCODED_CWD"
printf "HANDOFF_DIR='%s'\n" "$HANDOFF_DIR"
