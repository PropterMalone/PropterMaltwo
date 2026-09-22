#!/usr/bin/env bash
# is-headless-transcript.sh — classify a Claude Code transcript as headless automation
# vs an interactive session.
#
# Signal: the session-meta `entrypoint` field on the first message line.
#   "cli"      → interactive human session
#   "sdk-*"    → a `claude -p` / SDK headless run (cron jobs, scheduled agents,
#                recurring /loop runs, anything unattended)
#
# Exit 0 = headless (entrypoint present and != "cli").
# Exit 1 = interactive ("cli") OR indeterminate. Indeterminate fails SAFE to
#          "interactive" so callers never silently skip or hide a real session on
#          a parse miss — over-including in an audit beats hiding a lost session.
#
# Used by the /wrap-stale back-fill to decide whether a session is gradeable: a
# calibration row for an unattended run is noise, not data.
#
# Usage: is-headless-transcript.sh <transcript.jsonl>
#
# WHY this is grep and not a JSON parser: transcripts run to megabytes, the field
# is on the first line, and `grep -m1` stops there. Parsing the file to answer a
# yes/no question costs more than the question is worth.
set -euo pipefail

t="${1:?usage: is-headless-transcript.sh <transcript.jsonl>}"
[ -f "$t" ] || exit 1

# entrypoint appears on the first real message line; grep -m1 stops at first hit (fast).
ep=$(grep -m1 -o '"entrypoint":"[^"]*"' "$t" 2>/dev/null | sed -E 's/.*:"([^"]*)"/\1/') || true

[ -n "$ep" ] || exit 1        # indeterminate → treat as interactive
[ "$ep" = "cli" ] && exit 1   # interactive
exit 0                        # headless automation
