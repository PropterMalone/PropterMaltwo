# The memory system

This is the part that makes sessions cohere over time. Without it, every session
starts cold. With it, a session opens by reading an index, knows what you were
doing, what you've decided, and how you like to work, and closes by writing the
deltas back.

Two pieces do the work: a **portable file convention** plus host-specific
**loading and lifecycle adapters**. The content does not belong to any provider.
How it enters a session differs by host.

## 1. Host loading: automatic versus explicit

| Host/profile | Memory behavior |
|---|---|
| Claude Code/full | Native, version/config-dependent auto-memory. The conventional per-project path is `$CLAUDE_HOME/projects/<encoded-cwd>/memory/`. |
| Codex/standard or full | Adapted explicit reads and writes. Set `PROPTERMALTWO_MEMORY_DIR` or name the root in project `AGENTS.md`. |
| Polytoken/standard or full | Adapted explicit reads and writes using the same convention; no provider or model is pinned. |
| Codex or Polytoken/core | Memory is not admitted. |
| Copilot/core preview | Persistent memory and lifecycle skills are unsupported. |

For Claude Code, `<encoded-cwd>` is the project path with slashes turned to
dashes, so a home session and a project session get different memory roots.
Claude can auto-load `MEMORY.md` and expose its memory instructions at session
start. Verify that behavior on the installed version before relying on it.

Codex and Polytoken do **not** infer or depend on that Claude path. Their global
instructions and `kickoff`/`wrap` adapters resolve memory from the nearest
project instruction first, then `PROPTERMALTWO_MEMORY_DIR`; if neither is set,
they ask instead of guessing. The same portable tree can be shared deliberately,
or each host/project can use a separate tree. The adapter never requires Claude
Code, Anthropic, `claude -p`, transcripts, or `~/.claude` runtime state.

The standard profile installs `templates/MEMORY.md` into PropterMaltwo's neutral
shared data home as a bootstrap source. It does not create personal memory or
choose its location for you.

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

The lifecycle surface is host-admitted rather than assumed portable:

- **`kickoff`** — session start. Reads the hot `MEMORY.md` plus one recent
  relevant handoff, reports bounded local state, and asks the agenda. Codex and
  Polytoken use thin adapters that require an explicit root, keep the pass
  read-only, and do not run external integrations by default.
- **`wrap`** — session end. Updates only changed memory, writes a concise dated
  `handoff_YYYY-MM-DD.md`, verifies the working tree, and reports what remains.
  The Codex and Polytoken adapters never automatically commit, push, publish,
  discard work, send messages, or launch review subagents.
- **`retro`** — Claude Code only in this milestone. It performs periodic safety
  review, memory maintenance, pattern extraction, and calibration review. Codex
  and Polytoken do not install it, and Copilot has no lifecycle skills.

Both kickoff variants name `roster.md` and `topics.md` as on-demand indexes and
open them only when the requested work is absent from the hot tier. This pointer
must be explicit because a bounded orientation should not read the whole tree.

Files these rituals maintain, alongside the typed memories:

| File | Role |
|------|------|
| `handoff_YYYY-MM-DD.md` | The last session's "what I did / what's next", read at kickoff if recent |
| `calibration.md` | Running log of confident predictions vs. outcomes (see `rules/quality.md`) |
| `dev_estimates.md` | Pre-commit time estimates vs. actuals (see CLAUDE.md "don't anchor on human timelines") |
| `patterns.md` | Recurring how-to patterns worth not re-deriving |
| `lessons.md` | Mistakes + what was learned |

## Bootstrapping a fresh machine

1. Choose a memory root. Claude users may adopt the host-created per-project
   root. Codex and Polytoken users must set `PROPTERMALTWO_MEMORY_DIR` or name the
   root in the project's `AGENTS.md`.
2. Copy `templates/MEMORY.md` (or the installed neutral shared template) into the
   root and fill the hot index. Create `roster.md` and `topics.md` beside it when
   the hot tier first needs to demote entries.
3. On standard/full Claude, Codex, or Polytoken, run `kickoff` at session start
   and `wrap` at session end. For explicit-read hosts, confirm the skill reports
   the intended root before allowing writes.
4. Keep memory outside public repositories unless its contents are meant to be
   public. It often holds intent, preferences, and external pointers that source
   control cannot reconstruct.

Not sure what a *good* entry looks like? `templates/examples/` has filled samples
(a session handoff, a feedback memory with **Why:**/**How to apply:**, a calibration
log); copy their shape, not their content.
