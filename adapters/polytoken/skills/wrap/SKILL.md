---
name: wrap
description: Close a Polytoken session by updating an explicitly configured memory root and concise handoff, verifying the working tree, and reporting remaining work without automatic commits, pushes, cleanup, or outbound actions.
---

# Wrap

Invoking wrap authorizes edits inside the resolved memory root for calibration,
project memory, backlog, lessons, and a handoff. It does not authorize commits,
pushes, publishing, sending messages, deleting files, discarding changes,
changing providers/models, or editing Polytoken configuration.

## Resolve memory

Use the nearest project `AGENTS.md`, then `PROPTERMALTWO_MEMORY_DIR`. If neither
names a memory root, ask before writing. Never infer another host's memory path.

## Close the session

1. Summarize only the live conversation, observed repository state, and tool
   output. Do not assume external transcript or usage services.
2. Insert a concise newest-first note under `## Session Notes` in
   `calibration.md` when present. Never append beneath footer sections.
3. Update only memory files whose facts changed. Promote durable facts from the
   handoff into the appropriate topic file; omit facts derivable from code/git.
4. Write `handoff_YYYY-MM-DD.md` with `What was done`, `What needs doing next`,
   and `Key context`; add `-HHMM` if today's filename exists. Keep it under about
   2 KiB.
5. Run read-only `git status --short`, explain every remaining entry, and preserve
   work that may belong to another session.
6. For substantive code changes, run the documented project validation command
   if it has not already run. Report observed output only.
7. Check `list_jobs` when this session launched background work. Explain or cancel
   nothing without authorization. Record recommended ADR/review work in the
   handoff; do not launch a subagent automatically.

## Completion contract

Return exactly:

```text
### Shipped
### Validation
### Memory and handoff
### Working tree
### Background jobs
### Remaining
```

Name every file written and command run. State `None` for empty sections. Do not
commit, push, publish, send an outbound message, or invoke an integration. Stop
after the summary.
