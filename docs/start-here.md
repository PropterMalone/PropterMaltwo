# Start here (the skinny version)

You can adopt the core of PropterMaltwo in any agentic tool — Claude Code,
Codex, Polytoken, Cursor, or a plain chat window — without running the
installer. The installer exists for multi-host power users who want
transactional safety, translated identity hooks, and admission checks. The
practices below are the part that changes how the work feels.

## The three ideas

1. **Memory lives outside the chat.** Keep a short hot index (`MEMORY.md`, one
   line per active project or high-use topic), colder `roster.md`/`topics.md`
   indexes opened only on demand, and one file per durable note with simple
   frontmatter. Chat context is disposable; continuity is durable. The full
   convention is documented in [memory-system.md](memory-system.md).
2. **Two rituals bound every session.** A bounded **kickoff** at the start
   re-orients from the index plus the latest handoff instead of re-reading
   everything. A **wrap** at the end writes a dated handoff with what was done,
   the exact next action, blockers, and decisions — and touches nothing else.
3. **Actions have boundaries.** Draft-first: the agent may prepare an email, a
   commit, a change, or a task, but sending, pushing, publishing, assigning, and
   deleting require separate explicit authorization. Capture, interpretation,
   and action are three distinct steps, never one.

## What to copy

| File(s) | What it gives you |
|---|---|
| `rules/quality.md`, `rules/testing.md`, `rules/glossary.md`, `rules/comms.md` | Working doctrine: calibration, test discipline, shared terms, project-scoped comms sweeps. Put them wherever your host reads instructions. |
| `templates/MEMORY.md` and `templates/examples/` | A seed for your memory root, with filled-in samples of a handoff, a feedback note, and a calibration log. |
| [memory-system.md](memory-system.md) | The manual for the convention: the two-tier index, typed notes, what not to store. |
| [adhd-and-agentic-work.md](adhd-and-agentic-work.md) | Why this exists. Worth reading even if ADHD is not your context — it is about interruption and resumption. |
| [connected-work.md](connected-work.md) | Read this before wiring any communications, calendar, or meeting-recording tool into an agent. |

Setup is deliberately small:

1. Create a memory directory outside any repository you push (or one per
   project), copy in `templates/MEMORY.md`, and fill the hot index with your
   active work. The template's auto-load wording describes Claude Code; on
   other hosts nothing loads until your instructions point at the root.
2. Point your agent at it: name the root in your project instruction file, or
   set `PROPTERMALTWO_MEMORY_DIR` if you later use the installed adapters.
3. Place the four rules where your host loads instructions.
4. Run the two skeletons below as custom instructions, slash commands, or plain
   prompts until they are habit.

## Host-agnostic session skeletons

These are starting points, not the installed skills — the host adapters add
native structure, subagent contracts, and read-boundaries.

**Kickoff (start of session):**

> Read `<memory-root>/MEMORY.md` and the most recent `handoff_*.md` if it is
> less than a week old. Read nothing else from memory. Report, one line each:
> active threads touching this project, anything the handoff flags as blocked
> or waiting, and the current work-tree state. Then ask me what we are working
> on. Do not start external integrations, send anything, or write to memory.

**Wrap (end of session):**

> Update only the memory entries that changed today. Write
> `<memory-root>/handoff_YYYY-MM-DD.md` — if that file already exists today,
> write `handoff_YYYY-MM-DD-HHMM.md` instead; never overwrite an earlier
> handoff. It contains: what was done, the exact
> next action, what is blocked and on whom, and decisions made with their
> reasons. Verify the working tree is clean or tell me exactly what is dirty.
> Do not commit, push, publish, send, delete, or discard anything.

## Standing instructions: the action boundary

The four rules do not carry the action boundary — in the full environment it
lives in host-specific instruction files. Adopt it as standing instructions in
whatever host you use, in words close to these:

> You may prepare drafts, commits, patches, replies, tentative events, and task
> suggestions. Sending, publishing, pushing, assigning another person, accepting
> terms, and deleting or discarding work each require my explicit,
> action-specific authorization first. Preparing a thing is not doing it.

## When you want the machinery

If you run work across several hosts, want installs that roll back cleanly, or
want push/commit identity guards translated to a new host, read the
[README](../README.md) and the per-host setup pages. If you run one host and
adopt the practices above, you already have most of the value.

An honesty note: the installer is not the product. The files and the habits
are. The machinery exists because this environment is depended on daily across
several hosts and needed to become safe to reinstall and honest about what is
actually verified.
