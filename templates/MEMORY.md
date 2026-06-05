# Memory Index

Last verified: <date>

Orientation file — read at session start. Points to everything else. Keep it an
*index*, not a store: one line per entry, content lives in the linked files.
(Lines past ~200 may be truncated when this is auto-loaded — stay concise.)

## Project Index

One row per active project. Detail lives in per-project memory dirs (auto-loaded
when you `cd` into that project). Keep the status cell to a sentence or two.

| Project | Deploy | Status |
|---------|--------|--------|
| example-app | (where it runs) | (one-line state; link to a topic file like [example-app.md](example-app.md)) |

## Topic Index

Cross-cutting topics that aren't tied to one project.

| Topic | File |
|-------|------|
| Feedback rules | feedback-index.md |
| Calibration log | calibration.md |
| Decisions | decisions.md |
| Lessons | lessons.md |
| Patterns | patterns.md |
| Dev-time estimates | dev_estimates.md |

## Memory Layout

- **This dir** — cross-project topics, backlog, patterns, lessons.
- **Per-project dirs** (`<claude-config>/projects/<encoded-cwd>/memory/`) — project-specific
  state, auto-loaded when you're in that project's directory.
- **Error log** — error-log.md

See docs/memory-system.md for how the whole system works.
