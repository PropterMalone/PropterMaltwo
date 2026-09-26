---
name: kickoff
description: Orient a new or resumed Codex session from an explicitly configured memory root, bounded local repository probes, and recent handoffs, then state context and ask for the agenda.
---

# Kickoff

Kickoff is read-only. It never sends messages, changes configuration, starts
external integrations, commits, pushes, or edits memory.

## Resolve memory explicitly

1. Use the memory root named by the nearest applicable project `AGENTS.md`.
2. Otherwise use `PROPTERMALTWO_MEMORY_DIR` when set.
3. If neither identifies a root, state `Memory: unconfigured` and ask the user
   for a path. Do not guess a host-private directory.

Do not assume memory auto-loaded. From the resolved root:

- read `MEMORY.md` (the hot index);
- select the newest relevant `handoff_*.md` only if it is at most three days old;
- if no recent handoff exists, read only the newest entry in `calibration.md`
  and the project topic named by the hot index;
- read `roster.md` or `topics.md` only when the user's named work is absent from
  the hot index;
- never sweep the full memory tree.

## Bounded local probes

Run independent read-only probes in parallel when useful:

- `git status --short`;
- `git log -1 --oneline`;
- the host's job list only when the handoff names background work;
- at most three projects from the recent handoff when the last memory is older
  than two days, using only status, latest log, and targeted TODO searches.

External mail, chat, calendar, task, browser, remote-trigger, and queue probes
are capability-gated and opt-in. Run none during kickoff unless the user asks
and the integration is configured. Never invent a result for an unavailable
probe.

## Output

Return one compact state block with:

- project and memory root (or `unconfigured`);
- newest handoff/calibration context;
- observed dirty-tree or background-work state;
- blockers and stale information, clearly labeled.

Then ask what is on the agenda and stop. Do not continue into exploratory work.
