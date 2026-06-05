---
name: docket
description: Daily planner — time-aware plan coordinating the user's day and Claude's day, with calendar awareness and queue integration
---

> **INTEGRATION STUB.** This skill wires Claude Code to an external tool/account that you must supply and configure: **a personal planner CLI + a queue tool + calendar access (the real setup uses bespoke `docket` + `phyllis` CLIs)**. It ships as a working example of the integration pattern, not a turnkey feature. See `docs/integrations.md` for what to install and how to plug in your own credentials. Without **a personal planner CLI + a queue tool + calendar access**, this skill won't run — that's expected.

Generate a daily plan that assigns tasks to calendar free slots, identifies Claude autonomous work, and signals reservations to your background-queue tool. The example setup uses two bespoke local CLIs: a planner (`<planner-cli>`, called `docket` in the real install) and a background-queue/scheduler (`<queue-cli>`, called `phyllis` in the real install). Follow these steps exactly:

## 1. Fetch data (parallel)

Run all of these simultaneously:

- **Todoist**: Use `find-tasks-by-date` (a Todoist MCP tool) with startDate "today" to get overdue + upcoming tasks. Also use `find-tasks` to get undated p1/p2 tasks. (Substitute `td` CLI calls from the `todoist-cli` skill if you don't run the MCP.)
- **Planner CLI**: Run your planner's dry-run command to get the plan output (which reads `backlog.md`, `slush.md`, queue state, and calendar internally). In the example install this is `node --import tsx ~/Projects/<planner-cli>/src/cli.ts plan --dry-run`. Point this at your own planner binary/script.

## 2. Estimate missing durations

Check fetched Todoist tasks for missing durations. For any task without a duration set:

1. Estimate how long the task will take based on its content, description, and project context. Use these rough buckets:
   - Quick admin (email, phone call, signup): 10-15min
   - Small fix, config change, short write-up: 30min
   - Focused task (code fix, document review, research): 60min
   - Deep work (new feature, exploration, complex debugging): 120min
   - Large project session (architecture, multi-file refactor): 180min
2. Use `update-tasks` (or `td task update --duration`) to set the duration on each task (format: "30m", "1h", "2h", etc.)
3. Report what you estimated: "Set durations: TaskA→30m, TaskB→2h, TaskC→15m"

Skip recurring tasks — their duration is usually stable and should be set manually.

## 3. Enhance with Todoist data

The CLI dry-run doesn't include Todoist data (no API token configured). Merge the Todoist tasks into the plan:

1. Parse the CLI output to see what's already scheduled from backlog + queue
2. Add Todoist tasks that aren't duplicated by backlog items:
   - Overdue Todoist tasks → prepend to scheduled blocks or flag prominently
   - Today's Todoist tasks → fit into free slots, using their duration estimates for block sizing
   - Recurring tasks → mention in a compact section
3. Note any Todoist/backlog duplicates (same topic appearing in both)

## 4. Present the plan

Render the combined plan with these sections:

```
# Docket — YYYY-MM-DD

## Schedule
  8:00 AM – 10:00 AM  [Block label]
    - [TODAY] [Project] Task name
    - [TODAY] [T] Todoist task

  (gap: meeting 10:00-10:30)

  10:30 AM – 12:00 PM  [Block label]
    - [THIS WEEK] Task name

## Claude Autonomous
  [Claude] Task name (Xmin, size)

## Reservations → Queue
  HH:MM – HH:MM [intensity] reason

## Queue Status
  Window: X% | Weekly: X% | Queued: N tasks

## Unscheduled (N)
  - [TIER] [Project] Task name
  ... top 15, then count of remainder

## Todoist Recurring
  - Task name — due MM/DD (recurrence)
```

Rules:
- Tag sources: `[T]` = Todoist, `[B]` = backlog, no tag = from CLI output
- Show calendar events as gaps between blocks (the CLI already accounts for them)
- Overdue items get prominent placement at the top of scheduled blocks
- Keep it scannable — no full descriptions unless there's a blocker to flag
- Empty sections: omit entirely
- After rendering, ask: "Want me to write this plan? (writes plan JSON + queue reservations to the planner's state dir, e.g. `~/.docket/`)"

## 5. Write plan (if approved)

Run the planner's write command (the example: `node --import tsx ~/Projects/<planner-cli>/src/cli.ts plan`, without `--dry-run`) to write:
- `~/.docket/plan-YYYY-MM-DD.json` — full plan
- `~/.docket/reservations.json` — signals to the queue tool
- `~/.docket/cache/todoist-YYYY-MM-DD.json` — Todoist snapshot

Also cache the Todoist data fetched via MCP by writing it to the cache file, so the CLI can replan later without MCP.
