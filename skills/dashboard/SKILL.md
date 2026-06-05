---
name: dashboard
description: The backlog — merged prioritized view of all actionable items from Todoist and backlog.md
---

> **INTEGRATION STUB.** This skill wires Claude Code to an external tool/account that you must supply and configure: **Todoist (via MCP or `td`) + a local `backlog.md` task file**. It ships as a working example of the integration pattern, not a turnkey feature. See `docs/integrations.md` for what to install and how to plug in your own credentials. Without **Todoist (via MCP or `td`) + a local `backlog.md`**, this skill won't run — that's expected.

Build a merged dashboard of all actionable items from Todoist and `backlog.md`. Follow these steps exactly:

## 1. Fetch data (parallel)

Run these simultaneously:
- **Todoist**: Use `find-tasks-by-date` (a Todoist MCP tool) with startDate "today" to get overdue + upcoming tasks. Also use `find-tasks` to get undated tasks across all projects. If you don't run the Todoist MCP, substitute the equivalent `td` CLI calls (`td today`, `td upcoming`, `td task list`) from the `todoist-cli` skill.
- **Backlog**: Read your local backlog file (e.g. `~/.claude/memory/backlog.md` — point this at wherever you keep yours). Parse Now/Soon/Someday tiers. Skip any items with strikethrough (`~~text~~`).
- **Slush**: Read an optional `slush.md` alongside the backlog if it exists. This contains session-wrap notes about tasks completed, changed, or added since the last dashboard. Match slush entries against Todoist tasks and propose updates (complete, reschedule, add) before rendering. Apply approved changes, then clear the processed slush entries.

## 2. Merge and prioritize

Combine all items into a single list using this priority ordering:

1. **Overdue** — Todoist non-recurring tasks with due date in the past, backlog Now items marked urgent
2. **Recurring** — Todoist recurring tasks (overdue + due today). Show as compact list. If all caught up, omit section.
3. **This Week** — Todoist tasks due within the next 7 days
4. **Action Items** — Backlog Now tier items, high-priority undated Todoist tasks (p1/p2)
5. **Upcoming** — Backlog Soon tier items, medium-priority Todoist tasks (p3), dated items beyond this week
6. **Personal (undated)** — Todoist p4 undated tasks that aren't dev/project work
7. **Someday** — Collapsed summary from backlog Someday tier (count + brief list of names, not full descriptions)

## 3. Render output

Render in **reverse urgency order** — least urgent at top, most urgent at bottom. The user sees the bottom of the output last, so urgent items land closest to their cursor.

Use this exact format:

```
## Dashboard — YYYY-MM-DD

### Someday (N items)
Dev: brief comma-separated list of project names...

### Personal (undated)
- [T] Task name
- ... (N more)

### Upcoming
- [B] Task name
- [T] Task name — due MM/DD

### Action Items
- [B] Task name — context/blockers
- [T] Task name

### This Week
- [T] p2 Task name — due MM/DD

### Recurring
- [T] p3 Task name — due MM/DD (every weekday)

### Overdue
- [T] p1 Task name — due MM/DD
- [B] Task name — context
```

Rules:
- Tag every item: `[T]` = Todoist, `[B]` = backlog.md
- Show Todoist priority only for p1/p2/p3 (skip p4 label, it's default)
- Show due dates as MM/DD for Todoist items that have them
- Include blocker info from backlog items where noted
- If a backlog item duplicates a Todoist task (same topic), show only once with both tags `[T][B]`
- Someday section: collapsed by default — just count + brief names. Say "expand with /dashboard someday" or similar.
- Exclude any project you keep Todoist-only (e.g. an ideas-capture project) entirely — those stay in Todoist only.
- Keep it scannable. No full descriptions — just enough context to know what the item is.
- Empty sections: omit entirely.
