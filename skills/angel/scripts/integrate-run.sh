#!/usr/bin/env bash
# ADR-20 composed state owner: build -> dispatch/validate -> render -> finalize.
set -euo pipefail

usage() {
  printf 'usage: integrate-run.sh RUN_DIR [--resume|--retry-reducer|--clone-retry]\n'
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi
if (( $# < 1 || $# > 2 )); then
  usage >&2
  exit 2
fi

RUN_DIR="$1"
ACTION="${2:-}"
case "$ACTION" in
  ""|--resume|--retry-reducer|--clone-retry) ;;
  *)
    echo "integrate-run: unknown action: $ACTION" >&2
    usage >&2
    exit 2
    ;;
esac
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$(realpath -- "$RUN_DIR")"

if [[ "$ACTION" == "--clone-retry" ]]; then
  CLONE_DIR="$(python3 "$SCRIPT_DIR/clone-integration-run.py" "$RUN_DIR")"
  echo "integrate-run: cloned immutable reviewed inputs to $CLONE_DIR" >&2
  exec "$0" "$CLONE_DIR"
fi

if [[ "$ACTION" == "--retry-reducer" ]]; then
  python3 - "$RUN_DIR" <<'PY'
import json,sys
from pathlib import Path
d=Path(sys.argv[1]); s=json.loads((d/'findings-snapshot.json').read_text())
if not s.get('integration_degraded') or (d/'verification').exists() or any(f.get('verification') for f in s.get('findings',[])):
    raise SystemExit('retry refused: run is not pristine degraded output; use --clone-retry')
disp=d/'dispositions.json'
if disp.exists():
    rows=json.loads(disp.read_text())
    if any(isinstance(v,dict) and v.get('disposition')!='no-record' for k,v in rows.items() if k!='experiment'):
        raise SystemExit('retry refused: human dispositions exist; use --clone-retry')
PY
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p "$RUN_DIR/retry-history/$stamp"
  for name in report.md findings-snapshot.json integration-decisions.json; do
    [[ -f "$RUN_DIR/$name" ]] && cp "$RUN_DIR/$name" "$RUN_DIR/retry-history/$stamp/$name"
  done
elif [[ -f "$RUN_DIR/findings-snapshot.json" && "$ACTION" != "--resume" ]]; then
  echo "integrate-run: snapshot already exists; use --resume or the narrowly gated --retry-reducer" >&2
  exit 2
fi

if [[ ! -f "$RUN_DIR/integration-workset.json" ]]; then
  python3 "$SCRIPT_DIR/build-integration-workset.py" "$RUN_DIR"
fi
if [[ ! -f "$RUN_DIR/integration-decisions.json" || "$ACTION" == "--retry-reducer" ]]; then
  "$SCRIPT_DIR/dispatch-integration.sh" "$RUN_DIR"
fi
python3 "$SCRIPT_DIR/validate-integration-decisions.py" \
  "$RUN_DIR/integration-workset.json" "$RUN_DIR/integration-decisions.json"
if [[ ! -f "$RUN_DIR/findings-snapshot.json" || "$ACTION" == "--retry-reducer" ]]; then
  if [[ "$ACTION" == "--retry-reducer" ]]; then
    python3 "$SCRIPT_DIR/render-integration.py" "$RUN_DIR" --retry
  else
    python3 "$SCRIPT_DIR/render-integration.py" "$RUN_DIR"
  fi
fi
"$SCRIPT_DIR/finalize-run.sh" "$RUN_DIR"
printf 'finalized %s\n' "$(date --iso-8601=seconds)" >> "$RUN_DIR/PROGRESS"
