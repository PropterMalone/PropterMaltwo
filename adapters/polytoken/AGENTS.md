# PropterMaltwo global guidance for Polytoken

PropterMaltwo installs shared doctrine under `{{PROPTERMALTWO_HOME}}/shared/`.
Read these files before substantive work; more-specific project instructions may
narrow them:

- @{{PROPTERMALTWO_HOME}}/shared/rules/quality.md
- @{{PROPTERMALTWO_HOME}}/shared/rules/testing.md
- @{{PROPTERMALTWO_HOME}}/shared/rules/glossary.md
- @{{PROPTERMALTWO_HOME}}/shared/rules/comms.md

Do not duplicate their contents in project instructions.

## Memory

Polytoken does not auto-load PropterMaltwo memory content. Resolve the memory root
from the nearest project `AGENTS.md` or `PROPTERMALTWO_MEMORY_DIR`; ask if neither
names one. Read only `MEMORY.md` and a recent relevant handoff by default. Use
`roster.md` and `topics.md` only on demand. See
@{{PROPTERMALTWO_HOME}}/shared/docs/memory-system.md.

## Native composition

- Use Polytoken's shipped `subagent` tool for bounded delegation. Do not install
  or assume a custom subagent definition.
- Use the shipped `plan` facet to research and review a plan, then its
  `handoff_plan` flow to the shipped `execute` facet for implementation. This
  adapter does not copy, replace, or override either facet.
- Use only installed skills. Core admits `code` and `status`; standard/full also
  admit `kickoff` and `wrap`.
- Treat integrations as opt-in seams. Read
  @{{PROPTERMALTWO_HOME}}/shared/docs/integrations.md before using one.
- Never send an outbound message, push, publish, commit, discard work, or run a
  destructive command unless the user authorizes that specific action.
- Hooks are accident-prevention guardrails, not a security boundary. Installed
  is not the same as verified active; validate and exercise them after reload.
- Use the user's configured provider and model groups. Do not require Claude
  Code, Anthropic, Claude state, or any particular provider/model.
