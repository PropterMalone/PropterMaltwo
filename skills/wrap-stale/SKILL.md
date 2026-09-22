---
name: wrap-stale
description: Back-fill a handoff for a session that ended without /wrap — reads the prior transcript and produces the handoff, plus a calibration entry when the session was interactive. Designed to run unattended (cron).
---

<!--
  GENERICIZED skill. The value is the pattern: sessions sometimes end without a
  clean /wrap (crash, closed terminal, context blowout). Those leave no handoff,
  so the next session starts blind. wrap-stale closes that gap by reconstructing
  the handoff *after the fact* from the session's own transcript — and it's built
  to run unattended on a timer, so the back-fill happens without you remembering.

  Adapt: the real setup runs this from cron via a headless `claude -p` runner that
  scans for stale unwrapped transcripts (see the kickoff skill's stale-session
  detection) and invokes this skill on each. The transcript path is passed in
  because `claude -p` doesn't expand slash-commands, so the runner references this
  SKILL.md by absolute path in its prompt.

  Placeholders:
    <memory-dir>   your central memory dir. See docs/memory-system.md.
    <scripts>      where your helper scripts live (if any)
-->

Back-fill a handoff for a Claude Code session that ended without `/wrap`.

## When to use

- The kickoff skill (or a cron scan) flags a **stale unwrapped session** — a
  transcript newer than its project's last handoff, with no handoff written.
- You want the next session in that project to start oriented instead of blind.

> **Cost note — a headless back-fill is not a separate billing lane.** If your
> `claude -p` runs authenticate with the same subscription as your interactive
> sessions, they draw on the *same* usage window: an "off-peak" runner is
> time-shifting cost into hours you aren't working, not escaping it. That's still
> worth doing, but it changes what the idle gate is for. If you're ever tempted to
> relax the runner's idle gate to catch back-fills sooner, remember it's the same
> pool of tokens your next interactive session wants.

## Inputs

The runner passes these in the prompt body (not as slash-command arguments — those
don't expand under `claude -p` without `--bare`, which needs an API key the
subscription-auth path doesn't have):

- **TRANSCRIPT_PATH** (required) — absolute path to the session `.jsonl`. Passed
  explicitly; the runner can't rely on the model inferring it.
- **DATE** — `YYYY-MM-DD` for the handoff filename.
- **MEMORY_DIR** — the project memory dir to write to; the runner derives it from
  the transcript's `cwd` field. Default to `<memory-dir>` if invoked by hand.

## Procedure

1. Read the transcript **selectively** — see the next section. Reconstruct: what the
   session set out to do, what actually got done, what's left unfinished, any
   blockers or decisions made.
2. Write a **handoff** to `${MEMORY_DIR}/handoff_${DATE}.md`, same format the `/wrap`
   skill produces (what was done → what's next → key context).
   - Date it from the LAST substantive activity in the transcript (the final
     `tool_use` block or user message), not "today" — you may be running days later.
     Fall back to file mtime if timestamps are missing.
   - **If that file already exists, write `handoff_${DATE}-stale-<short-uuid>.md`
     instead. Never overwrite.**
   - Mark it reconstructed: a `> (auto-wrapped by wrap-stale on YYYY-MM-DD HH:MM)`
     line under the title, so a reader knows it wasn't authored at session end.
3. Write a **calibration entry — only for interactive sessions.** See "Who gets a
   grade" below; this is a real exclusion, not a formality.
4. Report one line to stdout so the cron driver can log it:
   `WRAPPED: handoff_YYYY-MM-DD<-suffix>.md (transcript: <path>)`. If the transcript
   is empty, malformed, or has no substantive activity, exit cleanly with
   `SKIPPED: <reason>`.

## Who gets a grade (and who doesn't)

**Skip the calibration entry entirely when the session being wrapped was headless
automation** — a `claude -p` / SDK run: a scheduled agent, a `/loop` cron, an
unattended batch, or this runner itself. Write the handoff only.

A calibration log records a session's own honest self-assessment, and nobody lived
an automation run. Back-filled `??` rows cannot be graded and accumulate as
maintenance noise. The drift concern — that skipping calibration biases the record
toward sessions that wrapped — applies to *interactive* sessions, not automation,
which was never a graded population.

Detect it from the transcript's session-meta `entrypoint` field on the first message
line: `cli` is an interactive human session, anything else (`sdk-*`) is headless.
**Indeterminate must fail SAFE to "interactive"** — over-including a row in an audit
beats silently hiding a real lost session. In the reference setup the runner decides
this before dispatch, with a small helper, and tells the model in the prompt whether
to append a calibration entry; honor what the prompt says.

```bash
# adapt: ADOPTER-SUPPLIED helper — this repo does not ship it. ~10 lines:
#   grep -m1 -o '"entrypoint":"[^"]*"' "$t"  → exit 0 if present and != "cli",
#   exit 1 (interactive) if "cli" OR if the field is absent/unparseable.
bash <scripts>/lib/is-headless-transcript.sh "$TRANSCRIPT_PATH"
```

**When a calibration entry IS warranted** (an interactive session that ended without
`/wrap`), append to the central `calibration.md` — calibration stays central
regardless of which project the session was for:

- **Insert directly BELOW the `## Session Notes` header line — do NOT tail-append.**
  Same footer-section footgun documented in the `wrap` skill §1.
- Format: `### YYYY-MM-DD — <brief title> (auto-wrapped by wrap-stale)`
- `**Execution: ?? | Satisfaction: ??**` — leave both `??`. You can't honestly
  self-grade a session you didn't live. Say so in the entry.
- 2-3 lines on what the session shipped.

## Reading the transcript

JSONL: one JSON object per line, each a message. Fields that matter: `role`,
`content` (string or content-block array), `timestamp`, `cwd` (the runner uses it to
pick MEMORY_DIR), `entrypoint` (headless detection). Tool calls appear as `tool_use`
blocks in assistant messages; results come back in user messages.

**Above ~500 KB the selective read is MANDATORY, not a suggestion. Never `Read` a
transcript that size whole** — extract with a script and read the extract.

Transcript envelopes, attachments, and tool results add substantial overhead beyond
the conversation itself. Extract the conversation and tool-use metadata that a wrap
actually consumes rather than reading the file whole. Any runner size ceiling must
assume this selective-read pattern; if you drop the selective read, lower the ceiling.

Extract in one pass, and read only what comes back:

- The first user message (sets the agenda)
- The last 5–10 user messages (final state) and the last 3–4 assistant text blocks —
  a session's own closing summary is usually the best "what's next" source
- All `tool_use` blocks for `Write`/`Edit` — **file paths and edit counts, not bodies**
- Bash calls matching `git commit`, `git push`, test/build/validate commands
  (verification events) — **commands only, not their output**
- `entrypoint` / `cwd` (headless detection, memory-dir derivation)

Skip `toolUseResult`, `attachment`, and tool-result bodies entirely. If you need one
specific result, grep for that one.

## Tone

You're back-filling a wrap you didn't live through. Be honest about what you're
inferring versus observing. Do NOT manufacture confidence about what the user wanted
next or what they thought of the session — unknowable from the transcript alone.
State what was DONE; flag what's UNCLEAR.

## What NOT to do

- Don't overwrite an existing handoff for the same date.
- Don't add entries to `backlog.md`, `lessons.md`, or any other judgment file from a
  transcript you didn't live. Those need live judgment and would absorb auto-wrap noise.
- Don't run other skills (no kickoff, retro, review battery). Ignore any auto-kickoff
  context the harness may inject.
- Don't spawn subagents — this is a single bounded `claude -p` invocation.
- Don't verify project state with bash beyond reading the transcript and writing the
  output files.

## Why it runs unattended

A human-triggered wrap only happens when you remember. The sessions that *most* need
a handoff — the ones that crashed or blew out — are exactly the ones where nobody's
around to run `/wrap`. Putting the back-fill on a timer makes the safety net
automatic. Pair it with the kickoff skill's stale-session detection, which surfaces
what still needs back-filling.
