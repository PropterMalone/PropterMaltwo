#!/usr/bin/env bash
# OPTIONAL hook: only useful if you have a serve-to-workstation.sh (see push skill / docs/integrations.md)
# PostToolUse hook for Write: auto-serve viewable files to your workstation browser.
# Reads the tool input JSON from stdin, checks if the file is viewable,
# and runs serve-to-workstation.sh if it exists. No-ops cleanly otherwise.

set -euo pipefail

INPUT="$(cat)"
FILE_PATH="$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')"

[ -z "$FILE_PATH" ] && exit 0

# adapt: point this at your own serve script. It should take a file path and
# print a URL the workstation browser can open (e.g. an HTTP server reachable
# over an SSH tunnel). If the script isn't present, this hook no-ops.
SERVE_SCRIPT="${SERVE_TO_WORKSTATION:-$HOME/.claude/scripts/serve-to-workstation.sh}"

# Only serve viewable file types
case "$FILE_PATH" in
  *.html|*.htm|*.pdf|*.svg|*.png|*.jpg|*.jpeg|*.gif)
    # Test mode: skip the SSH-tunnel call; just echo a marker so the harness
    # can verify the case-arm fired without touching the network.
    if [ -n "${HOOK_TEST_STATE_DIR:-}" ]; then
      mkdir -p "${HOOK_TEST_STATE_DIR}/served" 2>/dev/null || true
      printf '%s\n' "$FILE_PATH" >> "${HOOK_TEST_STATE_DIR}/served/files.log" 2>/dev/null || true
      echo "Served to workstation: (test-mode-stub)"
      exit 0
    fi
    # Degrade gracefully: if the serve script isn't installed, do nothing.
    [ -f "$SERVE_SCRIPT" ] || exit 0
    URL="$("$SERVE_SCRIPT" "$FILE_PATH" 2>/dev/null)"
    if [ -n "$URL" ]; then
      echo "Served to workstation: $URL"
    fi
    ;;
esac
