---
name: kickoff
description: Session kickoff — orient from memory, state understanding, ask agenda
---

<!--
  GENERICIZED skill. The choreography (orient-from-memory → probe background
  work → state understanding → ask agenda) is the value; only personal specifics
  are swapped for <placeholders>. Adapt the integration commands to your own
  tools or delete the steps you don't use.

  Placeholders:
    <memory-dir>   your central memory dir. Claude Code derives a per-project
                   memory path from the cwd; the central one is the project
                   memory dir for your home/`~` sessions. See docs/memory-system.md.
    <dev-box>      the machine Claude Code runs on
    <workstation>  where you physically sit (browser, OAuth callbacks)
    <queue-tool>   an example background-task queue (swap for yours, or delete)
    <comms-source> an example inbox/chat/meeting source (Gmail/Slack/etc.)
-->

Session kickoff. Get oriented fast.

## 1. Orient (parallel reads)

Already auto-loaded: `MEMORY.md`. If your memory has grown large enough that you've
split it into tiers, MEMORY.md is the **hot tier only** (active projects + high-use
topics); the full portfolio and full topic index live in separate files (e.g.
`roster.md` for every project including dormant/shipped ones, `topics.md` for the
complete cross-cutting topic list) in the same memory dir, NOT auto-loaded. When the
user names a project or topic not in `MEMORY.md`, open the cold-tier file to find it —
that's the on-demand full index, not a "speculative read." (This two-tier split is
worth adopting once MEMORY.md's line-count starts crowding the truncation threshold;
document the decision to split it, e.g. in a `docs/decisions/` entry, so future
sessions know why the index is smaller than the portfolio.)

Read in parallel:
- Glob for `handoff_*.md` in the per-project memory dir (or `<memory-dir>` if running from `~`). Read if <3 days old.
- `patterns.md` — only if modified in the last 3 days (check mtime), otherwise skip.
- The active-style override file, if one exists — surface the active style in the state block (the `style` skill sets it; CLAUDE.md flags it as a session-start check but it has to actually happen here).

If no handoff found, read `calibration.md`'s latest entry (just the last note, not the whole file) and the per-project topic file if in a specific project.

Do NOT read: `lessons.md`, `assets.md`, `backlog.md`, `roster.md`, `topics.md`, or other files speculatively — they're on-demand lookups, not part of the default orient pass.

## 1.4. Stale-session detection + retro-stale status

If you wire up the optional helper scripts (a stale-session checker and a
retro-stale status file), run them in parallel here:
```bash
# adapt: example helper that scans transcripts for sessions that ended without /wrap
bash <scripts>/check-stale-sessions.sh
```

**Stale sessions** — if the check output is non-empty, surface in the state block, including the transcript path: "Stale unwrapped session(s) detected — `<date>` in `<project>` (transcript: `<path>`). A background back-fill job will pick them up at the next cron tick; or invoke the `wrap-stale` skill directly with the transcript path." Note: an unattended `claude -p` back-fill may share your interactive quota window depending on your auth setup, so a cron path that runs during idle windows time-shifts that cost off your active session.

**Retro-stale status — restrict to your home/`~` sessions if retro is a home-level activity for you** (i.e., project-scoped kickoffs skip this check; if retro dates start slipping under that scoping, reconsider running the check everywhere). If in scope, also check for a retro-stale status file:
```bash
cat <state-dir>/retro-stale-status.json 2>/dev/null
```
If the JSON file exists and `issue_count > 0` or `days_overdue > 0`, surface in the state block: "Retro overdue (Nd) — issue_count issue(s) flagged: <list issues by name>." If `days_overdue >= 0` but `issue_count == 0`, just: "Retro due (was YYYY-MM-DD); deterministic checks clean." Negative `days_overdue` with zero issues = not due, say nothing. If the file is absent: skip — the runner may not be wired to cron yet.

(Both halves are optional plumbing. If you don't run these helpers, delete this section — the core orient/state/agenda loop stands on its own.)

## 1.5. Background-job probe

If the handoff or most recent calibration entry flags a running background task (tmux run, `/loop` session, scheduled trigger, queued task, overnight batch, long-running `claude -p`), probe its live status. The goal is concrete status — "the embed job is at 58% as of 11:27" beats "check the embed job" — in the state summary.

Probes to run in parallel (skip any that don't apply):

- **tmux**: `tmux list-sessions 2>/dev/null`; for any session matching a name in the handoff, `tmux capture-pane -pS -15 -t <name>`
- **Task queue** (`<queue-tool>` is an example — swap for your own background queue, or delete): list pending tasks, e.g. `<queue-tool> queue list`. If it's a cwd-relative CLI (e.g. wraps `tsx`), `cd` into its project dir first — running it from an absolute path elsewhere can fail silently.
- **In-session cron jobs**: `CronList` tool — shows in-session scheduled tasks
- **Scheduled remote triggers**: `RemoteTrigger` with `action: list` — shows cron-based remote agents
- **Long-running processes**: `ps -eo pid,etimes,cmd --sort=-etimes 2>/dev/null | awk '$2 > 600 && $2 != "ELAPSED"' | grep -E 'node|python|claude|curl' | grep -v grep | head -10`
- **Orphan in-flight reviews**: grep the memory dir for `in flight` notes (`grep -rn "in flight" <memory-dir>/MEMORY.md <memory-dir>/handoff_*.md 2>/dev/null | head -10`) and check the referenced report path. If the path exists and looks complete: the wrap-time background review completed but the notification never landed in this session — read the report briefly and update the in-flight entry with the verdict + finding counts. If the path is gone (e.g., `/tmp/` cleared on reboot): clean up the entry as orphaned. Without this, "in flight" notes from prior wraps stay forever.

Skip entirely if the handoff mentions no background work.

## 1.6. Gap sweep

If the most recent handoff is >2 days old (or there's no handoff and calibration's last entry is >2 days old), the memory may miss recent work.

**Scope rule:** spawn at most **3** Explore subagents — *not* one per active project (a mature memory index lists dozens; fanning out wastes the window). Scope to projects mentioned in the most recent handoff's "What was done" / "What needs doing next" sections. If the handoff is silent on which projects matter, pick the 3 with the most-recent uncommitted git activity.

Replace `{{HANDOFF_DATE}}` in the prompt below with the actual date string (`YYYY-MM-DD`) from the handoff filename — don't leave the placeholder for the subagent to interpret.

> "Look at `~/Projects/<name>`. Report under 80 words: most recent commit and its message, any uncommitted changes, any unfinished work flagged in TODO/FIXME comments or in local `backlog.md`-style notes added since {{HANDOFF_DATE}}. If nothing interesting, say 'no deltas'. Do NOT read full source files — stick to `git log`, `git status`, and grep."

Collect summaries. Flag anything unexpected in the state block.

Skip if the last handoff is ≤2 days old — recent memory is authoritative.

## 2. Comms sweep (skip if this isn't a project with external comms)

This step pulls actionable items from your inboxes/chat/meeting sources. The
tools below are EXAMPLES — swap `<comms-source>` for whatever you use (email,
Slack, a meeting-notes service), or delete the whole step if you don't want
kickoff touching comms.

**Delta-only sweep.** Query each source only for items since the last sweep, using a small timestamp-tracker file as state. Never query "last N days" unconditionally — that wastes tokens re-reading items from earlier sessions. A helper that returns `max(last_swept, now - 7 days)` keeps a stale state file from triggering a huge fetch.

After a successful fetch on each source (even if zero items), mark it swept so the next session starts from there.

**Pre-check: auth.** If a source needs OAuth (e.g. a Google Workspace `gws`-style CLI), check token validity before calling it. If expired, skip that source, note "auth expired — reauth needed:" and show the login command. Reauth happens in `<workstation>`'s browser; for a localhost OAuth redirect from a headless `<dev-box>`, use an SSH reverse tunnel so the callback reaches the listener. Continue with the other sources even if one is down.

**Fetch in parallel**, summarizing actionable items only:
- **Chat** (e.g. Slack): use the delta timestamp as the `after:` floor. 0 hits → print "no new" and skip the summary; else summarize, then mark swept. If a prior turn handed the user a draft message in this channel, re-read the target thread/DM to verify whether it posted AND what was *actually sent* before referencing it — a user can silently edit-and-send a draft in the channel's own compose box, same as email.
- **Email**: query with `after:<delta>`. 0 hits → skip; else summarize actionable items, then mark swept.
- **Meeting notes** (e.g. a transcription service): use the delta timestamp as the query floor (small limit). 0 hits → skip; else summarize, then mark swept.

If all sources are empty, just print "Comms: nothing new" and move on — this is the goal case.

## 3. State + agenda

Briefly state: project/context, recent session context (from handoff or calibration), flags (retro due, blockers). Include window/context state from the statusline if visible.

Retro check: if `Next due:` in CLAUDE.md is today or past, mention once — "Retro due (was YYYY-MM-DD)." (If you scoped the retro-stale check to home/`~` sessions in step 1.4, apply the same scoping here.)

Ask what's on the agenda. No exploratory tool calls.
