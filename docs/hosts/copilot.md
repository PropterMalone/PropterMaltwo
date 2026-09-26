# GitHub Copilot host setup (preview)

The Copilot adapter is **preview**, repository-scoped, and instructions-only.
Only `core` is accepted. It is deliberately excluded from `--host all`.

## Prerequisites and install

Choose an explicit Git repository or project directory:

```bash
./install.sh --host copilot --profile core --project /path/to/project
./install.sh --host copilot --profile core --project /path/to/project --apply
./install.sh --host copilot --profile core --project /path/to/project --doctor
```

The project receives exactly five artifacts:

- `.github/copilot-instructions.md`;
- `.github/proptermaltwo/rules/{quality,testing,glossary,comms}.md`.

No global file or `AGENTS.md` is installed.

## Merge point

An existing `.github/copilot-instructions.md` is never overwritten. The installer
stages `.github/copilot-instructions.md.proptermaltwo.example`; review and merge
that fragment manually. The four namespaced rule files remain installer-managed.

## Verify

```bash
./install.sh --host copilot --profile core --project /path/to/project --doctor
```

Doctor verifies structure and reports preview maturity. This release has no
host-runtime activation gate for Copilot, so the documentation makes no live
behavior claim.

## Known gaps

Skills, hooks, custom agents, subagents, MCP servers, permissions enforcement,
persistent memory, kickoff/wrap, and global installation are unsupported or
not tested. The adapter does not claim first-class parity with Claude Code,
Codex, or Polytoken.

## Rollback and uninstall

```bash
./install.sh --host copilot --profile core --project /path/to/project --uninstall
./install.sh --host copilot --profile core --project /path/to/project --uninstall --apply
```

Uninstall removes only unchanged managed files. User-modified instructions or
rules remain with warnings. If a prior project instruction file was replaced,
the transaction ledger restores its immutable original backup when safe.
