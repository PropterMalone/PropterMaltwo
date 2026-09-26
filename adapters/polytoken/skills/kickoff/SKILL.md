---
name: kickoff
description: Orient a new or resumed Polytoken session from an explicitly configured memory root, bounded local probes, recent handoffs, and live jobs, then state context and ask for the agenda.
---

# Kickoff

Kickoff is read-only. It never sends messages, edits memory, changes host
configuration, commits, pushes, or starts an external integration.

## Resolve memory explicitly

1. Use the memory root named by the nearest applicable project `AGENTS.md`.
2. Otherwise use `PROPTERMALTWO_MEMORY_DIR` when set.
3. If neither identifies a root, state `Memory: unconfigured` and ask the user
   for a path. Do not guess another host's state directory.

Do not assume memory auto-loaded. From the resolved root:

- read `MEMORY.md` (the hot index);
- select the newest relevant `handoff_*.md` only when at most three days old;
- otherwise read only the newest `calibration.md` entry and project topic named
  by the hot index;
- consult `roster.md` or `topics.md` only when the named work is absent from the
  hot index;
- never sweep the full memory tree.

## Bounded local probes

Run independent read-only probes in parallel when useful:

- `git status --short` and `git log -1 --oneline`;
- `list_jobs` only when the handoff names background work;
- at most three projects from the recent handoff when memory is older than two
  days, using only status, latest log, and targeted TODO searches.

Mail, chat, calendar, task, browser, remote-trigger, and queue probes are opt-in
and capability-gated. Run none during kickoff unless the user asks and the tool
is available. Never invent results for unavailable tools. Do not launch a
subagent for the default orientation pass.

## Output

Return one compact state block with project, memory root (or `unconfigured`),
recent handoff/calibration context, observed dirty-tree or job state, and any
blocker or stale fact. Then ask what is on the agenda and stop.
