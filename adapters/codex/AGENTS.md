# PropterMaltwo global guidance for Codex

PropterMaltwo installs shared doctrine under `{{PROPTERMALTWO_HOME}}/shared/`.
Before substantive work, read these files; project instructions may narrow them:

- `{{PROPTERMALTWO_HOME}}/shared/rules/quality.md`
- `{{PROPTERMALTWO_HOME}}/shared/rules/testing.md`
- `{{PROPTERMALTWO_HOME}}/shared/rules/glossary.md`
- `{{PROPTERMALTWO_HOME}}/shared/rules/comms.md`

Use targeted reads. Do not copy their text into another instruction file.

## Memory

Codex does not auto-load PropterMaltwo memory. Resolve the current memory root
from the nearest project `AGENTS.md` or `PROPTERMALTWO_MEMORY_DIR`. If neither
names one, ask the user before reading or writing memory. At session start read
only `MEMORY.md` and a recent relevant `handoff_*.md`; use `roster.md` and
`topics.md` only for on-demand lookup. The convention is documented at
`{{PROPTERMALTWO_HOME}}/shared/docs/memory-system.md`.

## Host behavior

- Use Codex's native instructions, permissions, and subagent tools.
- Use only installed skills. The core profile admits `code` and `status`; the
  standard/full profiles also admit `kickoff` and `wrap`.
- Treat integrations as opt-in seams. Read
  `{{PROPTERMALTWO_HOME}}/shared/docs/integrations.md` before using one, and do
  not assume its CLI, credentials, or connector exists.
- Never send an outbound message, push, publish, commit, discard work, or run a
  destructive command unless the user has authorized that specific action.
- Hooks are accident-prevention guardrails, not a security boundary. A hook's
  installation does not prove runtime activation; verify trust and behavior.
- Do not require Claude Code, Anthropic models, Claude state, or private machine
  configuration. Use the user's configured Codex model and account.
