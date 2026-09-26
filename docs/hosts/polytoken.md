# Polytoken host setup

Polytoken is a **first-class** PropterMaltwo host and the primary adapter.
`core` provides instructions, portable doctrine, `code`, and `status`;
`standard` adds explicit-read memory, `kickoff`, `wrap`, and GitHub identity
hooks. `full` currently equals `standard` artifact for artifact.

## Prerequisites and install

- Polytoken installed and configured with the provider/model groups you choose.
- Python 3 for the shared hook bridge in `standard`/`full`.
- Optional overrides: `XDG_CONFIG_HOME` and `PROPTERMALTWO_HOME`.

```bash
./install.sh --host polytoken --profile core
./install.sh --host polytoken --profile standard --apply
./install.sh --host polytoken --profile standard --doctor
```

The target defaults to `$XDG_CONFIG_HOME/polytoken` (normally
`~/.config/polytoken`). Skills are managed copies there, not symlinks.

## Installed paths and merge points

- `$XDG_CONFIG_HOME/polytoken/AGENTS.md` (or
  `AGENTS.md.proptermaltwo.example` on conflict).
- `$XDG_CONFIG_HOME/polytoken/skills/{code,status}` for core, plus
  `{kickoff,wrap}` for standard/full.
- `$XDG_CONFIG_HOME/polytoken/hooks.json` for standard/full.

The hook merge preserves unrelated array entries. Invalid JSON, an unsafe merge,
or a same-name foreign definition leaves the file unchanged and stages
`hooks.proptermaltwo.example.json`. The bridge defaults the guards to the sibling
`$PROPTERMALTWO_HOME/shared/hooks/github-identity-map.json`; the installer seeds
only `github-identity-map.example.json`, so copy and edit it (or set
`PROPTERMALTWO_GH_IDENTITY_MAP`) before publication. It does not consult
`~/.claude` by default. After manual merge run `/daemon-reload` or restart
Polytoken. A project can negate an inherited hook with
`"!proptermaltwo-gh-push-identity"` or
`"!proptermaltwo-gh-commit-author"` in `.polytoken/hooks.json`.

## Native composition

The adapter uses Polytoken's shipped `general-purpose` subagent and shipped
`plan`/`execute` facets. It installs no facet or subagent definitions. Use the
shipped plan facet for research/review and approve its `handoff_plan` into the
shipped execute facet. The `code` skill calls the shipped `subagent` tool and
returns its structured completion; no provider or model is pinned.

## Verify and reload

```bash
polytoken validate skill "$XDG_CONFIG_HOME/polytoken/skills/code"
polytoken validate skill "$XDG_CONFIG_HOME/polytoken/skills/status"
polytoken validate skill "$XDG_CONFIG_HOME/polytoken/skills/kickoff"
polytoken validate skill "$XDG_CONFIG_HOME/polytoken/skills/wrap"
polytoken doctor
./install.sh --host polytoken --profile standard --doctor
```

Core validates only `code` and `status`. Standard/full validates all four paths.
For `verified-active`, reload discovery/hooks and use the actual runtime to show:
managed skill discovery; a benign `shell_exec` proceeds; a fixture push-shaped
`shell_exec` is denied before side effects; and an unrelated non-shell tool does
not fire either identity hook. A skip remains `unverified`; it never becomes a
static downgrade or a pass.

`python3 tests/polytoken_release_gate.py` checks fresh local evidence against the
machine binding, admission runner and executable bytes, host version, installed
config/skill/guard hashes, exact validator and probe argv, and raw runtime traces.
It is local tamper-evident freshness validation, not cryptographic remote
attestation: an actor who controls the evidence, executable, gate invocation,
and local filesystem can synthesize matching state. It protects this release
workflow against stale, skipped, failed, cross-machine, changed-input, and
label-only evidence; it is not a security boundary against a malicious local
writer.

## Memory, gaps, and integrations

Set `PROPTERMALTWO_MEMORY_DIR` or name a memory root in project `AGENTS.md`.
Polytoken does not auto-load that content. No adapter asset requires Claude Code,
Anthropic, `~/.claude`, or a particular provider/model. Only `code`, `status`,
`kickoff`, and `wrap` are admitted in standard/full; all other skills and
integrations are excluded. See [Integrations](../integrations.md).

## Rollback and uninstall

```bash
./install.sh --host polytoken --profile standard --uninstall
./install.sh --host polytoken --profile standard --uninstall --apply
```

Uninstall removes unchanged managed files/definitions and retains shared content
owned by another host. Modified files survive with a warning. Resolve any
transaction journal using the exact recovery command printed by doctor.
