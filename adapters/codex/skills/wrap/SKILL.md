---
name: wrap
description: Close a Codex session by updating an explicitly configured memory root and concise handoff, verifying the working tree, and reporting remaining work without automatic commits, pushes, cleanup, or outbound actions.
---

# Wrap

Invoking wrap authorizes edits inside the resolved memory root for calibration,
project memory, backlog, lessons, and a handoff. It does not authorize commits,
pushes, publishing, sending messages, deleting files, discarding changes, or
changing host configuration.

## Resolve memory

Use the nearest project `AGENTS.md`, then `PROPTERMALTWO_MEMORY_DIR`. If neither
names a memory root, ask before writing. Never infer a host-private memory path.

## Close the session

1. Summarize only facts from the current conversation, repository state, and
   command output. Do not assume transcript APIs or another host's session data.
2. Insert a concise newest-first note under `## Session Notes` in
   `calibration.md` when that file exists. Do not append below footer sections.
3. Update only memory files whose facts changed. Promote durable facts from the
   handoff into the appropriate topic file; do not duplicate derivable code or
   git history.
4. Write `handoff_YYYY-MM-DD.md` with `What was done`, `What needs doing next`,
   and `Key context`. If that filename exists, add an `-HHMM` suffix. Keep it
   under about 2 KiB.
5. Run read-only `git status --short`. Explain every remaining entry and do not
   alter work that may belong to another session.
6. For substantive code changes, run the project's documented validation command
   if it has not already run. Report observed output; never infer success.
7. If work suggests a decision record or review, add the recommendation to the
   handoff. Do not start a review subagent automatically.

## Completion contract

Return exactly:

```text
### Shipped
### Validation
### Memory and handoff
### Working tree
### Remaining
```

Name every file written and every command run. State `None` for empty sections.
Do not create a commit. Do not push or send any outbound message. Stop after the
summary.
