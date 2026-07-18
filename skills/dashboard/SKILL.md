---
name: dashboard
description: The backlog — merged prioritized view of all actionable items from a task manager and backlog.md
---

> **INTEGRATION STUB.** This skill wires Claude Code to an external tool/account that you must supply and configure: **a task-list API (the reference setup uses Google Tasks via the `gws` CLI) + a local `backlog.md` task file**. It ships as a working example of the integration pattern, not a turnkey feature. See `docs/integrations.md` for what to install and how to plug in your own credentials. Without **a task-list API + a local `backlog.md`**, this skill won't run — that's expected.

Build a merged dashboard of all actionable items from your task manager and `backlog.md`. Follow these steps exactly:

## 1. Fetch data (parallel)

Run these simultaneously:

- **Task manager** (the reference setup uses Google Tasks via the `gws` CLI, personal account, default config): resolve list IDs by title, then fetch open tasks from every list EXCEPT the excluded set:

  ```bash
  gws tasks tasklists list --params '{}' --format json
  ```

  Excluded lists: an ideas-capture list (ideas stay in their list, never rendered) and a personal-follow-up-queue list (e.g. a "Follow-up" list you use to flag things for the agent to investigate at the next retro — drained there, render only as a one-line count if non-empty, e.g. "Follow-up: 2 queued for next retro", never as top-level actionable items). Any other list (including a default "My Tasks" list where quick-adds from email/calendar land, and any new list you create) is included by default.

  For each included list:

  ```bash
  gws tasks tasks list --params '{"tasklist":"<id>","maxResults":100,"showCompleted":false}' --format json
  ```

  Note: `gws` prints a `Using keyring backend:` line before the JSON — strip to the first `{` before parsing.

- **Backlog**: Read your local backlog file (e.g. `~/.claude/projects/<encoded-home-path>/memory/backlog.md` — point this at wherever you keep yours). Parse Now/Soon/Someday tiers. Skip any items with strikethrough (`~~text~~`).

- **Slush**: Read an optional `slush.md` alongside the backlog if it exists. This contains session-wrap notes about tasks completed, changed, or added since the last dashboard. Match slush entries against your task manager and propose updates (complete, reschedule, add) before rendering. Apply approved changes, then clear the processed slush entries. Example mutations against a Tasks-API-style backend:

  ```bash
  # complete
  gws tasks tasks patch --params '{"tasklist":"<listId>","task":"<taskId>"}' --json '{"status":"completed"}'
  # reschedule
  gws tasks tasks patch --params '{"tasklist":"<listId>","task":"<taskId>"}' --json '{"due":"YYYY-MM-DDT00:00:00.000Z"}'
  # add (default to the Inbox list)
  gws tasks tasks insert --params '{"tasklist":"<inboxListId>"}' --json '{"title":"[p2] Task name","due":"YYYY-MM-DDT00:00:00.000Z"}'
  ```

  > **Gotcha with the Google Tasks API: you CANNOT clear a due date via patch.** `--json '{"due":null}'` is a silent no-op (the client drops the null; the API ignores it) — the patch "succeeds" but the date stays. To truly un-date a task (e.g. triaging a stale overdue item to "someday"), you must **delete + recreate without `due`**: capture `title`+`notes` first, delete the task, then insert with no `due` field. Verify after — the patch response echoes only changed fields, so a blank title in the response is normal, not corruption.

## 2. Priority convention

If your task backend has no native priority field (Google Tasks doesn't), encode priority as a title prefix: `[p1]`, `[p2]`, `[p3]`; no prefix = p4/default. Parse it off the title before rendering (show the priority label, not the bracket text). Hand-entered tasks may lack prefixes — treat as p4 and reconcile at retros (retro also revisits whether the tiering still works).

Due dates: a Tasks-API-style backend is often date-only (the `due` field's time portion is meaningless). If you migrated from a richer task manager, a due *time* from the old system can be preserved in `notes` (e.g. `[due time from <old-system>: …]`). Recurring items may live on a separate calendar rather than in the task list at all, if your task API can't express recurrence.

## 3. Merge and prioritize

Combine all items into a single list using this priority ordering:

1. **Overdue** — task-manager items with due date in the past, backlog Now items marked urgent
2. **This Week** — task-manager items due within the next 7 days
3. **Action Items** — Backlog Now tier items, high-priority undated task-manager items (p1/p2)
4. **Upcoming** — Backlog Soon tier items, p3 task-manager items, dated items beyond this week
5. **Personal (undated)** — unprefixed (p4) undated task-manager items that aren't dev/project work
6. **Someday** — Collapsed summary from backlog Someday tier (count + brief list of names, not full descriptions)

## 4. Render output

Render in **reverse urgency order** — least urgent at top, most urgent at bottom. The user sees the bottom of the output last, so urgent items land closest to their cursor.

Use this exact format:

```
## Dashboard — YYYY-MM-DD

### Someday (N items)
Dev: brief comma-separated list of project names...

### Personal (undated)
- [G] Task name
- ... (N more)

### Upcoming
- [B] Task name
- [G] Task name — due MM/DD

### Action Items
- [B] Task name — context/blockers
- [G] Task name

### This Week
- [G] p2 Task name — due MM/DD

### Overdue
- [G] p1 Task name — due MM/DD
- [B] Task name — context
```

Rules:
- Tag every item: `[G]` = task manager (adapt the letter to your backend, e.g. `[T]` for Todoist), `[B]` = backlog.md
- Show priority only for p1/p2/p3 (p4/unprefixed is default, no label)
- Show due dates as MM/DD for task-manager items that have them
- Include blocker info from backlog items where noted
- If a backlog item duplicates a task-manager item (same topic), show only once with both tags (e.g. `[G][B]`)
- Someday section: collapsed by default — just count + brief names. Say "expand with /dashboard someday" or similar.
- Keep it scannable. No full descriptions — just enough context to know what the item is.
- Empty sections: omit entirely.

> If you migrate task managers, note the cutover here: which list IDs map to which old projects, whether the old account stays live as a soak-period fallback, and where its credentials live if a re-check is ever needed.
