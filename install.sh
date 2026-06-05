#!/usr/bin/env bash
# Install the PropterMaltwo Claude Code environment into ~/.claude.
#
# Default is a DRY RUN — it prints what it would do and changes nothing.
# Pass --apply to actually write. Re-running is safe (idempotent); anything it
# would overwrite is first copied into a timestamped backup dir, and your
# existing settings.json is never clobbered.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${CLAUDE_HOME:-$HOME/.claude}"
TS="$(date +%Y%m%dT%H%M%S)"
BACKUP="$TARGET/.propter-maltwo-backup-$TS"
APPLY=0

usage() {
  cat <<EOF
PropterMaltwo installer

Usage:
  ./install.sh            Dry run — show what would happen, change nothing
  ./install.sh --apply    Install into \$CLAUDE_HOME (default: ~/.claude)
  ./install.sh --help     This message

Env:
  CLAUDE_HOME   Override the install target (default: \$HOME/.claude)

What it installs: CLAUDE.md, rules/, skills/, hooks/, templates/, scripts/,
statusline-command.sh, and settings.example.json. Conflicts are backed up to
\$CLAUDE_HOME/.propter-maltwo-backup-<timestamp>/ before being overwritten.
Your settings.json is never overwritten.
EOF
}

case "${1:-}" in
  --apply) APPLY=1 ;;
  --help|-h) usage; exit 0 ;;
  "") : ;;
  *) echo "unknown arg: $1" >&2; usage; exit 1 ;;
esac

say() { printf '%s\n' "$*"; }
is_exec_path() { case "$1" in hooks/*.sh|hooks/*.py|hooks/lib/*.sh|scripts/*|statusline-command.sh|skills/*/scripts/*) return 0 ;; *) return 1 ;; esac; }

# install_file <relpath-under-repo>
install_file() {
  local rel="$1" src="$REPO_DIR/$1" dest="$TARGET/$1"
  if [ "$APPLY" -eq 0 ]; then
    if [ -e "$dest" ]; then
      if ! cmp -s "$src" "$dest"; then say "  update  $rel   (existing backed up)"; fi
    else
      say "  add     $rel"
    fi
    return
  fi
  mkdir -p "$(dirname "$dest")"
  if [ -e "$dest" ] && ! cmp -s "$src" "$dest"; then
    mkdir -p "$(dirname "$BACKUP/$rel")"
    cp -p "$dest" "$BACKUP/$rel"
  fi
  cp -p "$src" "$dest"
  if is_exec_path "$rel"; then chmod +x "$dest"; fi
}

say "PropterMaltwo → $TARGET"
[ "$APPLY" -eq 0 ] && say "(dry run — pass --apply to write)"
say ""

# Top-level items to mirror into $TARGET, file by file.
while IFS= read -r f; do
  rel="${f#"$REPO_DIR"/}"
  install_file "$rel"
done < <(cd "$REPO_DIR" && find CLAUDE.md rules skills hooks templates scripts docs statusline-command.sh -type f 2>/dev/null | sed "s#^#$REPO_DIR/#")

# settings.example.json: ship the example; create settings.json only if absent.
install_file "settings.example.json"
if [ "$APPLY" -eq 1 ]; then
  if [ ! -e "$TARGET/settings.json" ]; then
    cp -p "$REPO_DIR/settings.example.json" "$TARGET/settings.json"
    say "  add     settings.json   (seeded from example — review it)"
  fi
else
  if [ ! -e "$TARGET/settings.json" ]; then
    say "  would seed settings.json from example (none present)"
  else
    say "  settings.json exists — would leave it, see settings.example.json to merge"
  fi
fi

say ""
if [ "$APPLY" -eq 0 ]; then
  say "Dry run — nothing written. Run './install.sh --apply' to install, then see Next steps."
else
  [ -d "$BACKUP" ] && say "Backed up overwritten files to: $BACKUP"
  say "Installed into $TARGET."

  # Post-install guidance (only after a real --apply).
  cat <<EOF

Next steps:
  1. Edit $TARGET/CLAUDE.md — replace the <placeholders> with your setup.
  2. If you already had a settings.json, merge in the "hooks" and "statusLine"
     blocks from settings.example.json (it was NOT overwritten).
  3. Bootstrap memory: copy templates/MEMORY.md into your memory dir
     (see docs/memory-system.md), then run /kickoff at session start.
  4. Wire any integrations you want — see docs/integrations.md.
EOF
fi
