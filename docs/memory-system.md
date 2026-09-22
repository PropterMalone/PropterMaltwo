# The memory system

This is the part that makes sessions cohere over time. Without it, every session
starts cold. With it, a session opens by reading an index, knows what you were
doing, what you've decided, and how you like to work, and closes by writing the
deltas back.

Two pieces do the work: **Claude Code's built-in auto-memory** (the engine) and a
**file convention** plus three **session skills** (the discipline layered on top).

## 1. The engine: built-in auto-memory

Claude Code ships a persistent, file-based memory system. It lives in your Claude
config dir under a per-project path derived from the working directory, e.g.:

```
~/.claude/projects/<encoded-cwd>/memory/
```

`<encoded-cwd>` is your project path with slashes turned to dashes, so a `~`
(home) session and a `~/Projects/foo` session get *different* memory dirs. The
home-session dir acts as your "central" memory; per-project dirs hold
project-local state and are auto-loaded when you're in that project.

The engine auto-loads `MEMORY.md` at the start of every session and gives the
model instructions for reading and writing typed memory files. You don't
configure the engine; it's there. This repo adds the *convention* and the
*rituals* that make it pay off.

This auto-loading behavior is version- and config-dependent, so verify the
memory dir actually auto-loads on your install before relying on it; if it
doesn't, the convention still works with a manually-created memory dir and
explicit reads at session start.

## 2. The convention: a two-tier index + typed memory files

### `MEMORY.md` is an index, not a store

It's always loaded, so it stays short: one line per entry, content in the linked
file. A starter lives at `templates/MEMORY.md`; copy it into your memory dir to
bootstrap (see install notes). Two tables carry most of it:

- **Project Index** — one row per active project: name, where it deploys, a
  one-sentence status that links to a per-project topic file.
- **Topic Index** — cross-cutting concerns (feedback rules, calibration,
  decisions, lessons, patterns) → the file that holds each.

Entries are `- [Title](file.md) — one-line hook`.

### Why one index stopped working, and the hot/cold split that replaced it

The auto-loaded index is **capped**: past a documented line/byte ceiling the tail
is simply dropped, silently and losslessly-for-the-loader. (Check your install's
current limit rather than trusting a number here; the mechanism is what matters,
not the constant.) One index holding every project and every topic grows past
that ceiling the moment the portfolio does — a few dozen projects and a topic
list in the hundreds is enough. The failure is the bad kind: nothing errors, the
index just stops including its last rows, and the session opens believing it read
everything.

Worse, the recurring fix was manual. Every retro included a "fold something down"
step to get back under the cap, which is maintenance the system created for
itself.

So the index splits into **two tiers**:

| Tier | File | Loaded | Holds |
|------|------|--------|-------|
| **Hot** | `MEMORY.md` | Automatically, every session | Only **active** projects (in flight now) and a **curated allowlist** of high-use topics. Terse: one line each. |
| **Cold** | `roster.md` | On demand | The **complete** project roster, every state — active, shipped, deployed-stable, on hold, abandoned. One line each. |
| **Cold** | `topics.md` | On demand | The **complete** topic index — every topic file, with a pointer. |

The hot tier is a *working set*, not a catalogue. Target it well under the cap
(a third of it is a comfortable bar) and let the cold files be unbounded. A
project leaving the hot tier isn't deleted; it moves to `roster.md`, which is
where the session goes looking when it needs something not in front of it.

Two rules keep the split from rotting:

1. **The cold tier is a known file path, not a hope.** The point is that a
   session can *open* `roster.md` when it needs the full list. Don't rely on the
   model spontaneously recalling that a file exists — the skills that need it
   name it explicitly in their own instructions.
2. **Promotion and demotion happen at `/retro`, on a stated rule.** Hot = worked
   on recently, or strategically central right now. Everything else is cold.
   Without a review step the hot tier silently regrows and you're back at the cap.

An **active/dormant rule** worth copying: hot if it's had commits in the last
three weeks *or* it's strategically central, minus anything shipped,
deployed-stable, on-hold, not-started, or abandoned. Cap the topic allowlist too
(~15, add-one-remove-one), for the same reason.

Deriving these files automatically from per-project cards is the obvious next
step and mostly a trap at small scale: the migration (authoring a card in every
project file) is the real work, and a generator that emits a stub-only index is
worse than the hand-maintained one. Hand-edit both tiers until hand-editing
measurably hurts.

### Each memory is its own file with frontmatter

```markdown
---
name: short-kebab-slug
description: one-line summary, used to judge relevance in future sessions, so be specific
metadata:
  type: user | feedback | project | reference
---

The memory body. Link related memories with [[other-slug]].
```

### Four types

| Type | Holds | Example |
|------|-------|---------|
| **user** | Who you are, your role, preferences, what you know, so the model tailors to you | "Deep Go background, new to this repo's React frontend; frame frontend explanations in backend analogues" |
| **feedback** | How to work: corrections *and* confirmed-good approaches. Lead with the rule, then **Why:** and **How to apply:** | "Integration tests must hit a real DB, not mocks. Why: a prior mock/prod divergence masked a broken migration." |
| **project** | Ongoing work, goals, incidents not derivable from code/git. Decays fast, so date it | "Merge freeze begins 2026-03-05 for the mobile release cut." |
| **reference** | Pointers to where info lives in external systems | "Pipeline bugs are tracked in the Linear project INGEST." |

**Save feedback from success, not just failure.** If you only record corrections,
you avoid old mistakes but drift away from approaches already validated. When the
user confirms an unusual call worked, write it down with *why*.

### What NOT to put in memory

Code patterns, architecture, file paths, git history, who-changed-what,
debugging fixes, anything already in CLAUDE.md. All of that is derivable by
reading the current repo. Memory is for what you *can't* reconstruct: intent,
preferences, decisions, external pointers. Memory records are also snapshots in
time. Verify a recalled fact against current reality before acting on it.

## 3. The rituals: kickoff / wrap / retro

Three skills (in `skills/`) operate the system:

- **`/kickoff`** — session start. Reads the hot `MEMORY.md` plus recent handoffs,
  surfaces background work and flags (retro due, blockers), states understanding,
  asks the agenda. Turns a cold start into an oriented one. It names `roster.md`
  and `topics.md` as the on-demand portfolio and topic indexes, and opens them
  only when the agenda needs something the hot tier doesn't carry — that pointer
  has to be explicit, because kickoff is otherwise instructed not to go reading
  extra files.
- **`/wrap`** — session end. Updates the calibration log, writes/updates memory
  for what changed, writes a dated `handoff_YYYY-MM-DD.md` so the next session
  picks up mid-stream, scans commits for decision-record candidates.
- **`/retro`** — every few days. Safety review, memory maintenance (prune stale,
  archive overflow), pattern extraction, and a scan of the dev-estimate log so
  calibration feeds back into future estimates.

Files these rituals maintain, alongside the typed memories:

| File | Role |
|------|------|
| `handoff_YYYY-MM-DD.md` | The last session's "what I did / what's next", read at kickoff if recent |
| `calibration.md` | Running log of confident predictions vs. outcomes (see `rules/quality.md`) |
| `dev_estimates.md` | Pre-commit time estimates vs. actuals (see CLAUDE.md "don't anchor on human timelines") |
| `patterns.md` | Recurring how-to patterns worth not re-deriving |
| `lessons.md` | Mistakes + what was learned |

## Bootstrapping a fresh machine

1. Make sure your memory dir exists (Claude Code creates the per-project one on
   first use; for the central home-session dir you can create it yourself).
2. Copy `templates/MEMORY.md` into it and start filling the two index tables.
   That's the hot tier. Create empty `roster.md` and `topics.md` beside it; they
   stay empty until the hot tier has something to demote, which is the right
   time to start them.
3. Run `/kickoff` at the start of sessions and `/wrap` at the end. The memory
   builds itself from there.

Not sure what a *good* entry looks like? `templates/examples/` has filled samples
(a session handoff, a feedback memory with **Why:**/**How to apply:**, a calibration
log); copy their shape, not their content.
