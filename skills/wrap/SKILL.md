---
name: wrap
description: End-of-session wrap — update calibration, memory, backlog, lessons
---

<!--
  GENERICIZED skill. The value is the ritual: grade the session honestly
  (calibration), update memory + backlog + lessons, settle the git tree, write
  a handoff for the next session, and reconcile any background work. Integration
  steps (queue tool, draft-diff review, auto-review) are EXAMPLES — adapt to
  your own tools or delete the ones you don't use.

  Placeholders:
    <memory-dir>   your central memory dir (Claude Code derives a per-project
                   one from the cwd; the central one is your `~`-session memory
                   dir). See docs/memory-system.md.
    <queue-tool>   an example background-task queue
    <review-skill> a code-review battery (the `/angel` skill here)
-->

Session wrap. Run through each step, skip what doesn't apply.

## 1. Calibration note (`calibration.md`)

Append under `## Session Notes`:
```
### YYYY-MM-DD — Brief title
**Execution: X | Satisfaction: Y**
What shipped + key mistake (if any). 2-3 lines max.
```
Grade honestly (A/B/C/D scale — definitions in `calibration.md`'s header). Don't deduct for external blockers.

**Grade perturbation rule:** If your initial grade lands on `B+`, `A-`, or `A`, force a one-notch counter-argument (`B+ → argue for B vs A-; A- → argue for B+ vs A; A → argue for A-`) before settling. The B+/A- pair is the dominant anchor in most calibration logs — that's round-number anchoring (see `rules/quality.md`). If the counter-argument resolves to "default feels right," downgrade by one notch. (This rule earns its keep once the log has enough entries to show clustering; until then, just grade and move on.)

**Trim rule:** If `## Session Notes` has >15 entries, archive the oldest 5 to `calibration-archive.md` (compressed to grade + one-liner) before appending the new entry. Keeps the live file lean and makes archival continuous instead of retro-dependent.

## 2. Update memory files

All in one pass — touch only what changed this session. Batch the reads in parallel, then batch the edits in parallel (don't serialize):
- **Per-project memory** (the cwd's memory dir) — architecture decisions, status changes, test counts
- **Backlog** (`backlog.md`) — add new TODOs, strikethrough completed, adjust priorities
- **Lessons** (`lessons.md`) — only if mistakes were made
- **MEMORY.md index** — only if project status/deployment changed materially

<!-- adapt: a real setup also kept a "slush" file — a dated scratch buffer of changes
     destined for an external task manager, trimmed to a 7-day window and
     consumed by a dashboard skill. If you have an external task manager, add an
     equivalent step; otherwise this is just the backlog above. -->

## 3. Tidy the working tree

`git status` for the current project. Commit ready changes, discard junk, flag ambiguous. Skip for pure meta sessions.

## 3.5. Decision-record scan

If the current project has a `docs/decisions/` directory, scan the session's commit messages (`git log --since=<session-start>` or by the current branch's commits since main) for decision keywords:

```
\b(decided|chose|going with|rejected|adopt|adopting|deprecate|deprecating|switching to|instead of|tradeoff|opted|landed on|settled on)\b
```

(case-insensitive)

For each match, surface the commit + ask: "Decision record? (y / n / skip)".

- **y**: scaffold an ADR file at `docs/decisions/NN-<slug>.md` using `templates/adr-template.md`, with `id`/`name`/`date`/`commits` filled in. Surface the path so the user can complete the body.
- **n**: dismiss; the keyword was incidental
- **skip**: defer; don't ask again this session

Skip the entire step if:
- No `docs/decisions/` exists in the current project (per-project opt-in)
- No commits landed this session
- The matched commits are all reverts, version bumps, or pure style fixes

Keyword matching is noisy but cheap. False-positive friction is acceptable; missed decisions are not. A decision made via discussion only (no commit) won't be caught here — write it manually using the template.

**Iteration plan**: After 2–3 wraps using this step, evaluate hit rate vs. false-positive friction. If false-positives dominate, tighten the regex. If misses dominate, add structural checks (e.g., commits touching `architecture/` or `src/lib/api/`).

## 4. Handoff file

Write to the per-project memory dir (or `<memory-dir>` from `~`). Standard format: What was done, What needs doing next, Key context. **Soft size cap: ~2KB.** Bullet points, not paragraphs. Full session history belongs in `calibration.md`; the handoff is for next-session orientation, not logging — kickoff reads it in full and re-pays the token cost on each session-start.

If a handoff for today already exists, write to `handoff_YYYY-MM-DD-HHMM.md` with a current-time suffix (don't overwrite — multiple wraps per day are legitimate). Delete handoffs >7 days old. **If at 95% context, write this FIRST.**

## 5. Queue reconciliation (example integration — skip if you don't run a queue)

If you use a background-task queue (`<queue-tool>` is an example), check whether this session completed work that's queued:
```bash
<queue-tool> queue list
```
If any queued task overlaps with what was done this session, mark it done:
```bash
<queue-tool> queue done "<name-or-pattern>"
```
This prevents the queue from burning a window on work that's already finished. Delete this step if you don't run a queue.

## 6. Rate-limit annotation (example — skip if not applicable)

Only if the user mentioned hitting a rate limit this session, and only if your queue tool keeps a calibration log: manually append a `"throttled": true` entry to it so the scheduler learns. Automated hooks handle normal snapshots.

## 7. Draft-vs-sent review (example integration — skip if you don't draft messages)

If Claude drafts outbound messages (per CLAUDE.md, always to drafts, never sent directly) and logs each draft, you can learn the user's editing voice by comparing what was drafted to what the user actually sent. Wire a scanner that, for each drafted message, checks whether the user has since sent a message in the same thread:

```bash
# adapt: example scanner that diffs logged drafts against sent messages
python3 <scripts>/scan-draft-diffs.py
```

If a pending-diffs file exists and is non-empty, review each entry:

1. Read the pending file.
2. For each entry, compare `draft_body` vs `sent_body`. Identify what the user changed — phrasing, cuts, additions, tone shifts.
3. Append a dated block to a feedback memory file (e.g. `<memory-dir>/feedback-casual-email-voice.md`), matching its existing format (date, recipient, context line, bulleted changes, "kept intact" line). Keep it concise.
4. Do NOT promote anything to "Emerging patterns" from a single diff. Patterns promote only when a change appears in ≥3 independent diffs across different recipients — review the full log history before promoting.
5. Delete the pending-diffs file after processing.
6. Note in the session summary how many diffs were processed, and flag any newly-promoted patterns.

If the scanner errors (auth expired, etc.), it should exit cleanly — don't block wrap on this step. Delete the whole step if you don't draft messages.

## 7.5. Auto-review of shipped code (example integration with the review battery)

If this session shipped code — commits landed, or `git diff HEAD~N` against session start shows substantive changes — and the review battery (`<review-skill>`) did NOT already run in-session, kick off a trimmed review in the background.

Criteria:
- At least one commit in a project directory during the session
- Project has test/build infra (`package.json`, `Cargo.toml`, `pyproject.toml`, etc.) so pre-flight can run
- The diff is non-trivial (>20 lines, not just version bumps / lockfile updates)

Procedure:
- Spawn a background Agent (`run_in_background: true`) with subagent_type `general-purpose`
- Prompt: run a trimmed `<review-skill>` pass on `git diff HEAD~N HEAD` (N = commits this session), write the report to `/tmp/review-wrap-{project}-YYYY-MM-DD.md`
- Do NOT block the wrap on completion
- **As soon as the agent is launched, surface the report path in two places so it survives `/clear`:**
  1. Add a "Recent review" / "Pending (survives /clear)" section to the project's `MEMORY.md` with the date, status (`in flight` initially), and the report path. MEMORY.md auto-loads at next kickoff. **If running from `~` (no project context), write the in-flight note to `<memory-dir>/MEMORY.md`'s Topic Index instead, with a TTL note (`pending review — check by YYYY-MM-DD`).**
  2. Add an item to the active handoff's "What needs doing next" section noting the in-flight review and the report path.
  Without this step, a `/clear` after wrap loses all knowledge that a review was running, and the next session won't know to scan the report.
- When the agent's completion notification arrives (may be during or after the wrap summary): scan the report and **update the same MEMORY.md + handoff entries** with the verdict + finding counts (so they read "completed, here's what landed" rather than "in flight"). Severity-gated handling:
  - **Critical**: fix same-session. Do NOT defer to next session's handoff. Commit the fix, re-settle the tree, update the handoff to note what the review caught and how it was fixed, then re-wrap. The wrap grade absorbs the extra round trip; shipping a handoff with "fixed" framing over a known-broken architecture is worse.
  - **Important / Major**: trivial single-spot fixes can land same-session; complex ones add to the handoff "What needs doing next" with priority context, severity, and file:line pointers.
  - **Minor / Noted**: note the report path in the summary and move on.

Skip entirely if: no code shipped this session, project has no test/build infra, or the review battery already ran in-session.

## 8. Summary

Brief wrap: what was updated, grade + one-line rationale, items added to backlog.

## 8.5. Wrap-fail recovery

If `/wrap` crashed partway through (API blip, context overflow at 95%, hook timeout, manual interrupt), the system is in a known-but-inconsistent state. The next session's kickoff will surface stale-session symptoms but won't know if a partial wrap was attempted. Recovery procedure:

**Step-by-step survives-fail behavior** (use this as a checklist if asked "did the wrap land?"):

| Step | What it writes | Idempotent re-run? | If missing on retry |
|------|----------------|--------------------|--------------------|
| 1 calibration | `calibration.md` append | ✓ yes | Re-append — duplicate is rare and easy to spot |
| 2 memory updates | per-project memory, backlog, lessons, MEMORY.md | partial — each file independent | Re-do; each edit is its own commit |
| 3 git tidy | `git status` only by default | ✓ read-only | Re-run |
| 4 handoff | `handoff_YYYY-MM-DD.md` (or `-HHMM.md` if exists) | ✓ writes new file with timestamp suffix | Re-do — duplicate handoff is acceptable, diff to merge |
| 5 queue check | `queue done` | ✓ marking done twice is no-op | Re-run |
| 6 throttle annotation | manual jsonl append | partial | Skip on retry unless a rate-limit was the wrap-fail cause |
| 7 draft diffs | append to feedback file, delete pending file | ✓ pending-file deletion makes it idempotent | If pending file still exists, retry; if gone, step completed |
| 7.5 auto-review | spawn background agent + write in-flight note | NOT idempotent — would spawn 2 agents | Skip retry; kickoff probe (1.5) reconciles orphan in-flight notes |

**Recovery from cold (next session)**:
1. `git status -s <memory-dir>` and the per-project memory dirs — uncommitted changes from a wrap-in-progress
2. Run the stale-session checker (if wired) — confirms whether a handoff landed for the wrap-fail date
3. If a calibration entry exists but the handoff is missing: write the handoff manually using the calibration entry as source-of-truth for "what was done"
4. If an "in flight" review note predates the crash: kickoff section 1.5's reconcile path catches it

**Avoiding the failure mode**: at 95% context, write the handoff FIRST (it's step 4 in the normal order, but at 95% drop the rest and write step 4 only — it survives the wrap). Calibration can be back-filled next session.

## 9. Sign-off

**Running `/wrap` can itself be the conveyance of gratitude for the session's work** — closing the session properly instead of `/clear`-ing it is the gesture. If the user has framed it that way, future-Claude reading this skill should understand: if the user ran `/wrap`, the work was appreciated, whether or not it was said explicitly this session.

After delivering the wrap summary, stop. If the user thanks you, respond however feels genuine. Do NOT preempt with your own scripted thanks — that turns the ritual into ceremony and wastes the beat.
