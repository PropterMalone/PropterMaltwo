---
name: wrap-stale
description: Back-fill a handoff for a session that ended without /wrap — reads the prior transcript and produces the handoff + calibration entry. Designed to run unattended (cron).
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
-->

Back-fill a handoff for a Claude Code session that ended without `/wrap`.

## When to use

- The kickoff skill (or a cron scan) flags a **stale unwrapped session** — a
  transcript newer than its project's last handoff, with no handoff written.
- You want the next session in that project to start oriented instead of blind.

## Inputs

- **Transcript path** (required): the prior session's `.jsonl` transcript. Passed
  explicitly — the runner can't rely on the model inferring it.

## Procedure

1. Read the transcript. Reconstruct: what the session set out to do, what actually
   got done, what's left unfinished, any blockers or decisions made.
2. Write a **handoff** to the project's per-session memory dir, same format the
   `/wrap` skill produces (Review summary → what's done → what's next → key context).
3. Write a **calibration entry** — grade the session honestly (predicted vs actual,
   misses, lessons), same as a normal wrap. Stale back-fills must not skip this, or
   the calibration record silently drifts toward only-the-sessions-that-wrapped.
4. Note that this handoff was back-filled (not written live), so a reader knows it's
   reconstructed from the transcript rather than authored at session end.

## Why it runs unattended

A human-triggered wrap only happens when you remember. The sessions that *most*
need a handoff — the ones that crashed or blew out — are exactly the ones where
nobody's around to run `/wrap`. Putting the back-fill on a timer makes the safety
net automatic. Pair it with the kickoff skill's stale-session detection, which
surfaces what still needs back-filling.
