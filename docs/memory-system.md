# The memory system

This is the part that makes sessions cohere over time. Without it, every session
starts cold. With it, a session opens by reading an index, knows what you were
doing, what you've decided, and how you like to work — and closes by writing the
deltas back.

Two pieces do the work: **Claude Code's built-in auto-memory** (the engine) and a
**file convention** plus three **session skills** (the discipline layered on top).

## 1. The engine: built-in auto-memory

Claude Code ships a persistent, file-based memory system. It lives in your Claude
config dir under a per-project path derived from the working directory, e.g.:

```
~/.claude/projects/<encoded-cwd>/memory/
```

`<encoded-cwd>` is your project path with slashes turned to dashes — so a `~`
(home) session and a `~/Projects/foo` session get *different* memory dirs. The
home-session dir acts as your "central" memory; per-project dirs hold
project-local state and are auto-loaded when you're in that project.

The engine auto-loads `MEMORY.md` at the start of every session and gives the
model instructions for reading and writing typed memory files. You don't
configure the engine — it's there. This repo adds the *convention* and the
*rituals* that make it pay off.

This auto-loading behavior is version- and config-dependent, so verify the
memory dir actually auto-loads on your install before relying on it; if it
doesn't, the convention still works with a manually-created memory dir and
explicit reads at session start.

## 2. The convention: an index + typed memory files

### `MEMORY.md` is an index, not a store

It's always loaded, so it stays short: one line per entry, content in the linked
file. A starter lives at `templates/MEMORY.md` — copy it into your memory dir to
bootstrap (see install notes). Two tables carry most of it:

- **Project Index** — one row per active project: name, where it deploys, a
  one-sentence status that links to a per-project topic file.
- **Topic Index** — cross-cutting concerns (feedback rules, calibration,
  decisions, lessons, patterns) → the file that holds each.

Entries are `- [Title](file.md) — one-line hook`. Keep it under ~200 lines; the
tail gets truncated when auto-loaded.

### Each memory is its own file with frontmatter

```markdown
---
name: short-kebab-slug
description: one-line summary — used to judge relevance in future sessions, so be specific
metadata:
  type: user | feedback | project | reference
---

The memory body. Link related memories with [[other-slug]].
```

### Four types

| Type | Holds | Example |
|------|-------|---------|
| **user** | Who you are, your role, preferences, what you know — so the model tailors to you | "Deep Go background, new to this repo's React frontend — frame frontend explanations in backend analogues" |
| **feedback** | How to work: corrections *and* confirmed-good approaches. Lead with the rule, then **Why:** and **How to apply:** | "Integration tests must hit a real DB, not mocks. Why: a prior mock/prod divergence masked a broken migration." |
| **project** | Ongoing work, goals, incidents not derivable from code/git. Decays fast — date it | "Merge freeze begins 2026-03-05 for the mobile release cut." |
| **reference** | Pointers to where info lives in external systems | "Pipeline bugs are tracked in the Linear project INGEST." |

**Save feedback from success, not just failure.** If you only record corrections,
you avoid old mistakes but drift away from approaches already validated. When the
user confirms an unusual call worked, write it down with *why*.

### What NOT to put in memory

Code patterns, architecture, file paths, git history, who-changed-what,
debugging fixes, anything already in CLAUDE.md. All of that is derivable by
reading the current repo. Memory is for what you *can't* reconstruct: intent,
preferences, decisions, external pointers. Memory records are also snapshots in
time — verify a recalled fact against current reality before acting on it.

## 3. The rituals: kickoff / wrap / retro

Three skills (in `skills/`) operate the system:

- **`/kickoff`** — session start. Reads `MEMORY.md`, recent handoffs, surfaces
  background work and flags (retro due, blockers), states understanding, asks the
  agenda. Turns a cold start into an oriented one.
- **`/wrap`** — session end. Updates the calibration log, writes/updates memory
  for what changed, writes a dated `handoff_YYYY-MM-DD.md` so the next session
  picks up mid-stream, scans commits for decision-record candidates.
- **`/retro`** — every few days. Safety review, memory maintenance (prune stale,
  archive overflow), pattern extraction, and a scan of the dev-estimate log so
  calibration feeds back into future estimates.

Files these rituals maintain, alongside the typed memories:

| File | Role |
|------|------|
| `handoff_YYYY-MM-DD.md` | The last session's "what I did / what's next" — read at kickoff if recent |
| `calibration.md` | Running log of confident predictions vs. outcomes (see `rules/quality.md`) |
| `dev_estimates.md` | Pre-commit time estimates vs. actuals (see CLAUDE.md "don't anchor on human timelines") |
| `patterns.md` | Recurring how-to patterns worth not re-deriving |
| `lessons.md` | Mistakes + what was learned |

## Bootstrapping a fresh machine

1. Make sure your memory dir exists (Claude Code creates the per-project one on
   first use; for the central home-session dir you can create it yourself).
2. Copy `templates/MEMORY.md` into it and start filling the two index tables.
3. Run `/kickoff` at the start of sessions and `/wrap` at the end. The memory
   builds itself from there.

Not sure what a *good* entry looks like? `templates/examples/` has filled samples
(a session handoff, a feedback memory with **Why:**/**How to apply:**, a calibration
log) — copy their shape, not their content.
