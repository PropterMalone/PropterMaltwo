---
name: chain
description: Run a sequence of audits or audit-shaped tasks autonomously, each in a fresh subagent context. Each leg ships mechanical fixes, queues semantic findings to a per-chain backlog file, and triggers the next leg. Usage: /chain <name> [-- audit1 prompt | audit2 prompt | ...] OR /chain <name> (resumes existing chain).
---

An audit-chain pattern (e.g. legibility → time-awareness → coverage), tooled. Each leg of the chain is independent, gets a clean subagent context, and produces:
- Commits on the current branch (mechanical fixes)
- Appended entries in `<project-memory-dir>/chain-<name>-queue.md` (semantic findings). The project-memory dir is the per-project memory directory derived from cwd (e.g. `~/.claude/projects/<encoded-cwd>/memory/`).
- A short structured report back to the orchestrator

The orchestrator (this main session) sequences legs and writes a consolidated summary at the end. No /clear or /kickoff between legs — subagent isolation does what those used to do manually.

**This is autonomous.** Do not pause for user input between legs. Semantic findings get queued, not surfaced for live decision. The user reviews the queue file at their convenience after the chain completes.

## 1. Validate context

- Must be in a project directory (`~/Projects/*`, or wherever your repos live — adapt to your layout). If not, ask which project.
- Args required:
  - **First positional**: chain name (used for state file + queue file). Letters/digits/dashes only, max 32 chars.
  - **After `--`**: list of audit prompts separated by `|`. Each prompt is one leg. Required on first run; optional when resuming.

If `~/.claude/state/chains/<name>.json` already exists and `--` args are provided, abort with "Chain <name> exists. To resume, omit the prompts. To restart, delete the state file first."

## 2. Initialize state

If state file does not exist, create `~/.claude/state/chains/<name>.json`:

```json
{
  "name": "<name>",
  "project": "<project-dir-basename>",
  "projectPath": "<absolute project path>",
  "queueFile": "<absolute path to memory/chain-<name>-queue.md>",
  "started": "<ISO timestamp>",
  "current": 0,
  "steps": [
    { "prompt": "<audit 1 prompt>", "status": "pending", "report": null },
    { "prompt": "<audit 2 prompt>", "status": "pending", "report": null }
  ]
}
```

If queue file does not exist, create with header:

```markdown
# Chain queue: <name>

> Semantic findings deferred for human review. The chain itself is autonomous; this file is what each leg of the chain queues for later async review by the user.

Started: <ISO timestamp>
```

## 3. Run each leg

For each step where `status: "pending"`, in order:

1. Mark step `status: "running"` in the state file.
2. Spawn an Agent (`subagent_type: "general-purpose"`) with the leg prompt below. This is a foreground call — wait for the agent's report before advancing.
3. On agent completion:
   - Append the agent's queue entries (if any) to the queue file.
   - Mark step `status: "complete"`, save the agent's `report` field.
4. After commits land, run `npm run validate` (or the project's validate command) once. If it fails, mark step `status: "failed"`, log the failure to the queue file, and **abort the chain** — do not advance.

### Per-leg agent prompt (template)

```
You are leg N of M in audit chain "<name>" for project <projectPath>.

## Your audit prompt
<the leg's prompt>

## Mechanical vs. semantic — the only judgment call you make
- **Mechanical fix**: a finding with one obvious right answer that doesn't change product behavior visibly to the user (a typo, a missing test, a name fix, dead-code removal, format/lint fix, missing afterEach restore).
  → SHIP. Commit on the current branch with a focused message. Run the project's validate command before commit; if it fails, fix or back out.
- **Semantic finding**: anything that requires product judgment (UI copy, UX flow change, behavioral fix where the right answer depends on intent, schema changes, anything that breaks a public interface).
  → QUEUE. Append a structured entry to <queueFile>. Do NOT ship. Do NOT pause for user input.

## Queue file entry format
Each queued finding looks like this:

\```markdown
## <ISO date> — leg N: <one-line title>
**Severity**: P1/P2/P3 | **File**: path:line | **Why semantic**: <one line>

<2–4 line description of the finding and what decision is needed.>

**Pinned**: <test file path> if pinned by a test, else "no".
\```

If you ship a finding mechanically, commit it. Don't queue mechanical fixes.
If you queue a finding, optionally pin current behavior by adding a test. Pinning is recommended for real bugs.

## What to return to the orchestrator
A 200-word-max report:
- Findings count + how many shipped vs queued vs declined
- Test count delta (before vs after)
- Validate verdict (clean / errors / which)
- One-line summary of each shipped commit (SHA + subject)
- Any blockers that abort the chain

## Anti-patterns
- Don't over-mock. Real DB; mock unmanaged third-party HTTP boundaries via injected fetchFn.
- Don't add tests for hypothetical future code. The project rule is no future-proofing.
- Don't future-proof in production code. Adding optional config that only tests use is OK iff it mirrors an existing seam in the same codebase (sibling files use the same pattern).
- Don't push to origin. Just commit.
```

## 4. After all legs complete

Write a consolidated handoff summary to `<project-memory-dir>/handoff_<date>_chain-<name>.md`. Include:
- Each leg's report
- Total commits, total tests Δ, total queue entries
- Pointer to the queue file for human review

Mark the chain `status: "complete"` in the state file (don't delete — the queue file references it).

Notify the user once at the end via PushNotification:

```
chain <name> complete: <N> commits, <M> queued. Queue: <queueFile>
```

## 5. Resuming a chain

If `/chain <name>` is run with no `--` args and the state file exists:
- If any step is `status: "running"` (e.g., previous run was interrupted), prompt the user: "Step X was interrupted. Restart that step? (y/n)" — this is the ONE place a chain prompts; an interrupted leg may have left the tree in a partial state.
- Otherwise, continue from the first `pending` step.

## 6. Failure modes

- **Validate fails after a leg's commits**: abort chain, leave state at `failed`. User must manually un-fail (edit state file or re-run a leg). The queue file will have one entry naming the failure.
- **Subagent reports an error or doesn't return a parseable report**: log the raw output to the queue file, mark step failed, abort.
- **Project's validate command not detected**: try `npm run validate`, then `npm test`, then `cargo test`. If none work, fall back to "no validation" mode but flag prominently in the final summary.

## Examples

Three-audit chain on a project:

```
/chain quality-burn -- \
  "First-pass legibility audit: scan public/*.html surfaces against the 'first-pass legibility' principle in CLAUDE.md. Surface dead handlers, illegible buttons, jargon copy. Ship copy fixes; queue product-voice decisions." | \
  "Time-awareness substrate audit: verify that clock / relativeDate / scheduling primitives are actually exercised in the main loop and planning tools. Ship plumbing fixes; queue any UX changes." | \
  "Coverage gap-fill on the core path: find untested business logic on the handler → prompt → retrieval path. Ship colocated test files for files with zero tests; queue suggestions for tests inside files that already have suites."
```

Resume after interruption:

```
/chain quality-burn
```

## Why subagents and not /clear+/kickoff

- Subagents have isolated contexts by construction — that's what /clear was approximating manually.
- Subagents inherit the project working directory and tools — that's what /kickoff was bootstrapping.
- The orchestrator stays alive to handle the end-of-chain summary and any blocking failures, which a fully detached cron-based remote agent cannot.
- Future extension: a parallel mode (`/chain <name> --parallel`) where independent legs spawn together. Audit chains have so far been sequential (each can see the previous leg's commits) but coverage + legibility are independent.
