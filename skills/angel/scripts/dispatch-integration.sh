#!/usr/bin/env bash
# Isolated semantic reducer dispatch. Never falls back inline into the driver.
set -euo pipefail

RUN_DIR="${1:?usage: dispatch-integration.sh RUN_DIR}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"
WORKSET="$RUN_DIR/integration-workset.json"
FINAL="$RUN_DIR/integration-decisions.json"

if [[ ! -f "$WORKSET" ]]; then
  echo "dispatch-integration: missing $WORKSET" >&2
  exit 2
fi

reason=""
QUALIFICATION="${ANGEL_RUNNER_QUALIFICATION:-$HOME/.angel/integration-runner-qualified.json}"
RUNNER_FINGERPRINT="$(python3 "$SCRIPT_DIR/runner-fingerprint.py")"
BACKEND_DESCRIPTION=""
if ! BACKEND_DESCRIPTION="$(python3 "$SCRIPT_DIR/run-reducer-sandbox.py" --describe-backend 2>&1)"; then
  echo "$BACKEND_DESCRIPTION" >&2
  reason="no-qualified-runner"
fi
RUNNER_BACKEND=""
RUNNER_IDENTITY=""
RUNNER_MODEL=""
# Cross-process exit contract: run-reducer-sandbox 75 -> sharder 4 -> this
# typed degraded reason. Keep the names beside their numeric wire values.
RC_UNPROVABLE_RUNNER_CLEANUP=75
RC_SHARD_DEPTH_EXCEEDED=3
RC_SHARD_RUNNER_CLEANUP=4
if [[ -z "$reason" && -n "$BACKEND_DESCRIPTION" ]]; then
  IFS=$'\t' read -r RUNNER_BACKEND RUNNER_IDENTITY RUNNER_MODEL < <(
    python3 - "$BACKEND_DESCRIPTION" <<'PY'
import json,sys
d=json.loads(sys.argv[1])
print(d['backend']+'\t'+d['identity']+'\t'+d['model'])
PY
  )
fi
if [[ -z "$reason" ]] && ! python3 - "$QUALIFICATION" "$RUNNER_FINGERPRINT" \
    "$RUNNER_BACKEND" "$RUNNER_IDENTITY" "$RUNNER_MODEL" <<'PY'
import json,sys
try:
 d=json.load(open(sys.argv[1])); ok=(d.get('qualified') is True and d.get('model') == sys.argv[5]
     and d.get('auth') == 'chatgpt'
     and d.get('runner_fingerprint') == sys.argv[2]
     and d.get('runner_backend') == sys.argv[3]
     and d.get('runner_identity') == sys.argv[4])
except Exception: ok=False
raise SystemExit(0 if ok else 1)
PY
then
  reason="no-qualified-runner"
fi

if [[ -n "$reason" ]]; then
  python3 "$SCRIPT_DIR/validate-integration-decisions.py" "$WORKSET" \
    --write-union "$FINAL" --reason "$reason"
  python3 "$SCRIPT_DIR/record-integration-usage.py" "$RUN_DIR" --degraded-reason "$reason"
  exit 0
fi

printf 'reducer-dispatched %s\n' "$(date --iso-8601=seconds)" >> "$RUN_DIR/PROGRESS"
workset_tokens="$(python3 - "$WORKSET" <<'PY'
import json,sys
print(json.load(open(sys.argv[1])).get('metrics',{}).get('tokens_estimate',0))
PY
)"
if [[ "$workset_tokens" -gt 24000 ]]; then
  rc=0
  python3 "$SCRIPT_DIR/shard-integration.py" "$RUN_DIR" --mandate "$SKILL_DIR/reducer.md" \
    --schema "$SKILL_DIR/schemas/integration-decisions-v1.json" \
    --backend "$RUNNER_BACKEND" --runner-identity "$RUNNER_IDENTITY" || rc=$?
  if [[ "$rc" -eq 0 ]]; then
    python3 "$SCRIPT_DIR/validate-integration-decisions.py" "$WORKSET" "$FINAL"
    python3 "$SCRIPT_DIR/record-integration-usage.py" "$RUN_DIR" \
      --telemetry "$RUN_DIR/integration-telemetry.json"
    exit 0
  fi
  degraded="reducer-failed-twice"
  [[ "$rc" -eq "$RC_SHARD_DEPTH_EXCEEDED" ]] && degraded="shard-depth-exceeded"
  [[ "$rc" -eq "$RC_SHARD_RUNNER_CLEANUP" ]] && degraded="runner-cleanup-failed"
  python3 "$SCRIPT_DIR/validate-integration-decisions.py" "$WORKSET" \
    --write-union "$FINAL" --reason "$degraded"
  python3 "$SCRIPT_DIR/record-integration-usage.py" "$RUN_DIR" --degraded-reason "$degraded"
  exit 0
fi
failure=0
cleanup_failure=0
for attempt in 1 2; do
  out="$RUN_DIR/.integration-attempt-$attempt"
  mkdir -p "$out"
  python3 "$SCRIPT_DIR/run-reducer-sandbox.py" --mandate "$SKILL_DIR/reducer.md" \
      --workset "$WORKSET" --schema "$SKILL_DIR/schemas/integration-decisions-v1.json" \
      --output-dir "$out" --timeout 600 --backend "$RUNNER_BACKEND" \
      --expected-identity "$RUNNER_IDENTITY" \
      >"$out/client.stdout" 2>"$out/client.stderr" &
  child=$!
  printf '%s\n' "$child" > "$RUN_DIR/integration-runner.pid"
  (
    sleeper=""
    trap '[[ -n "$sleeper" ]] && kill "$sleeper" 2>/dev/null || true; exit 0' TERM INT HUP
    while kill -0 "$child" 2>/dev/null; do
      tmp="$RUN_DIR/.integration-heartbeat.tmp"
      printf '{"version":1,"status":"running","attempt":%s,"pid":%s,"updated_at":"%s"}\n' \
        "$attempt" "$child" "$(date --iso-8601=seconds)" > "$tmp"
      mv "$tmp" "$RUN_DIR/integration-heartbeat.json"
      sleep 30 &
      sleeper=$!
      wait "$sleeper" || exit 0
      sleeper=""
    done
  ) &
  heartbeat=$!
  rc=0
  wait "$child" || rc=$?
  kill "$heartbeat" 2>/dev/null || true
  wait "$heartbeat" 2>/dev/null || true
  if [[ "$rc" -eq "$RC_UNPROVABLE_RUNNER_CLEANUP" ]]; then
    cleanup_failure=1
    break
  fi
  if [[ "$rc" -eq 0 ]] \
    && python3 "$SCRIPT_DIR/validate-integration-decisions.py" "$WORKSET" "$out/integration-decisions.json"; then
    mv "$out/integration-decisions.json" "$FINAL"
    if [[ -f "$out/integration-telemetry.json" ]]; then
      mv "$out/integration-telemetry.json" "$RUN_DIR/integration-telemetry.json"
    fi
    python3 "$SCRIPT_DIR/record-integration-usage.py" "$RUN_DIR" \
      --telemetry "$RUN_DIR/integration-telemetry.json"
    printf '{"version":1,"status":"complete","attempt":%s,"updated_at":"%s"}\n' \
      "$attempt" "$(date --iso-8601=seconds)" > "$RUN_DIR/integration-heartbeat.json"
    exit 0
  fi
  tail -1 "$out/client.stderr" >&2 || true
  failure=1
done

if [[ "$cleanup_failure" -eq 1 ]]; then
  python3 "$SCRIPT_DIR/validate-integration-decisions.py" "$WORKSET" \
    --write-union "$FINAL" --reason runner-cleanup-failed
  python3 "$SCRIPT_DIR/record-integration-usage.py" "$RUN_DIR" \
    --degraded-reason runner-cleanup-failed
elif [[ "$failure" -eq 1 ]]; then
  python3 "$SCRIPT_DIR/validate-integration-decisions.py" "$WORKSET" \
    --write-union "$FINAL" --reason reducer-failed-twice
  python3 "$SCRIPT_DIR/record-integration-usage.py" "$RUN_DIR" \
    --degraded-reason reducer-failed-twice
fi
