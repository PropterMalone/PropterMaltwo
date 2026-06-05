#!/bin/bash
# One-time setup for a new machine after cloning your Claude Code config.
# Creates machine-specific dirs and symlinks that aren't tracked in git.
#
# ============================================================================
# OPTIONAL / AUTHOR-SPECIFIC — READ BEFORE RUNNING.
#
# This script is NOT required to use PropterMaltwo and reflects one specific
# layout choice. In particular it:
#   - creates a memory symlink that ASSUMES ~/.claude is itself a git repo with
#     a memory/ dir at its top level (it links projects/<slug>/memory ->
#     ../../memory). If your ~/.claude is not laid out that way, the symlink
#     points at nothing useful.
#   - clones a plugin marketplace from a git repo you configure.
#
# If you are not adopting that exact layout, you can safely DELETE this script.
# A stranger should read it through before running it.
# ============================================================================

set -euo pipefail

CLAUDE_DIR="$HOME/.claude"

echo "Setting up Claude Code config on $(hostname)..."

# 1. Create projects dir structure
# Claude Code derives a per-home "project slug" from the home dir path
# (e.g. /home/<you> -> home-<you>; C:\Users\<you> on Windows -> C--Users-<you>).
# Detect the right slug for this machine's home dir.
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
  # Windows Git Bash: C:\Users\<you> -> C--Users-<you>
  WIN_HOME=$(cygpath -w "$HOME")
  PROJECT_SLUG=$(echo "$WIN_HOME" | sed 's/[:\\]/-/g')
else
  # Linux/Mac: /home/<you> -> home-<you>
  PROJECT_SLUG=$(echo "$HOME" | sed 's|^/||; s|/|-|g')
fi

echo "Project slug: $PROJECT_SLUG"

PROJECT_DIR="$CLAUDE_DIR/projects/$PROJECT_SLUG"
mkdir -p "$PROJECT_DIR"

# 2. Symlink memory from project-specific path to shared top-level
if [ -L "$PROJECT_DIR/memory" ]; then
  echo "Memory symlink already exists"
elif [ -d "$PROJECT_DIR/memory" ]; then
  echo "WARNING: $PROJECT_DIR/memory is a real directory, not a symlink."
  echo "Back it up and replace with symlink manually if needed."
else
  ln -s ../../memory "$PROJECT_DIR/memory"
  echo "Created memory symlink: $PROJECT_DIR/memory -> ../../memory"
fi

# 3. Clone plugin marketplaces if missing
# adapt: replace the placeholders below with the marketplace repo(s) you use.
#   MARKETPLACE_NAME  — local dir name under ~/.claude/plugins/marketplaces/
#   MARKETPLACE_REPO  — the git URL you clone from (e.g. your own fork)
#   MARKETPLACE_UPSTREAM — optional upstream to track for updates (or leave blank)
PLUGINS_DIR="$CLAUDE_DIR/plugins"
mkdir -p "$PLUGINS_DIR/marketplaces"

MARKETPLACE_NAME="${MARKETPLACE_NAME:-<marketplace-name>}"
MARKETPLACE_REPO="${MARKETPLACE_REPO:-https://github.com/<your-gh-org>/<marketplace-repo>.git}"
MARKETPLACE_UPSTREAM="${MARKETPLACE_UPSTREAM:-}"

if [[ "$MARKETPLACE_REPO" == *"<your-gh-org>"* ]]; then
  echo "Skipping plugin-marketplace clone — set MARKETPLACE_NAME / MARKETPLACE_REPO first."
elif [ ! -d "$PLUGINS_DIR/marketplaces/$MARKETPLACE_NAME/.git" ]; then
  echo "Cloning $MARKETPLACE_NAME..."
  git clone "$MARKETPLACE_REPO" "$PLUGINS_DIR/marketplaces/$MARKETPLACE_NAME"
  if [ -n "$MARKETPLACE_UPSTREAM" ]; then
    git -C "$PLUGINS_DIR/marketplaces/$MARKETPLACE_NAME" \
      remote add upstream "$MARKETPLACE_UPSTREAM" 2>/dev/null || true
  fi
fi

# 4. Create empty session-manifest.jsonl if missing
if [ ! -f "$CLAUDE_DIR/session-manifest.jsonl" ]; then
  touch "$CLAUDE_DIR/session-manifest.jsonl"
  echo "Created empty session-manifest.jsonl"
fi

# 5. Create empty memory/sessions dir if missing
mkdir -p "$CLAUDE_DIR/memory/sessions"

echo ""
echo "Setup complete! Verify with: ls -la $PROJECT_DIR/memory/"
echo "Should show symlink to ../../memory"
