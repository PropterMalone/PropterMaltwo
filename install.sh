#!/usr/bin/env bash
# PropterMaltwo multi-host installer. Dry run is the default.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$REPO_DIR/scripts/proptermaltwo_installer.py" "$@"
