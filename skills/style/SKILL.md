---
name: style
description: Set, clear, or list communication styles. Usage: /style <name>, /style off, /style list
user-invocable: true
---

# Style Switcher

Set the active communication style globally (persists across sessions).

## Instructions

1. Parse the user's argument:
   - `/style list` — list available styles from `~/.claude/styles/*.md`
   - `/style off` or `/style none` — clear the active style
   - `/style <name>` — set the active style
   - `/style` (no arg) — show current active style

2. For **list**: glob `~/.claude/styles/*.md`, print filenames (without extension) and indicate which is active.

3. For **set**: check that `~/.claude/styles/<name>.md` exists. If it does, write `<name>` to `~/.claude/active-style`. If not, show available styles.

4. For **off/none**: write empty string to `~/.claude/active-style`.

5. For **show** (no arg): read `~/.claude/active-style`. If empty or missing, say "No active style." Otherwise show the active style name.

6. After setting or clearing, confirm the change. Remind the user that existing sessions need to re-read the style file — new sessions pick it up automatically.
