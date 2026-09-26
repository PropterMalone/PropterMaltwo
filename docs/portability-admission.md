# Portability and admission ledger

This ledger records checked-in product support, not machine-local activation.
`manifests/hosts-v1.json` is the machine-readable source. Runtime evidence lives
outside the manifest; only a fresh host-runtime pass may produce
`verified-active`.

Doctor is a presentation layer, not a trust root: until a host-specific
evidence validator is wired into it, doctor renders a claimed `verified-active`
as `unverified`. The Codex and Polytoken admission runners and the Polytoken
release gate are what establish and check that evidence today.

## Status vocabulary

- **first-class**: installer, doctor, rollback, deterministic contracts, and an
  actual-host activation path exist for the admitted surface.
- **preview**: useful bounded support exists, but the host lacks the first-class
  admission floor.
- **native**: supplied by the host and used directly.
- **adapted**: translated or wrapped and covered by host-specific contracts.
- **unsupported**: deliberately outside the admitted surface.
- **not-tested**: no checked-in product claim is made.

Static support never changes because a local binary is absent or a smoke is
skipped. Local activation is one of `verified-active`, `installed-untrusted`,
`inactive`, `unverified`, or `failed`. Installed configuration alone is not
proof of enforcement.

## Host/profile admission

| Host | Maturity | Accepted profiles | Default | Admitted skills |
|---|---|---|---|---|
| Claude Code | first-class | full | full | Existing complete Claude skill set |
| Codex | first-class | core, standard, full | standard | core: `code,status`; standard/full: `code,status,kickoff,wrap` |
| Polytoken | first-class | core, standard, full | standard | core: `code,status`; standard/full: `code,status,kickoff,wrap` |
| Copilot | preview | project-scoped core only | core | none |

Codex and Polytoken `full` equal `standard` artifact for artifact. `--host all`
means exactly `claude-code:full + codex:standard + polytoken:standard`; it accepts
no profile or project and excludes Copilot.

Claude Code is first-class by a stated grandfathering exception to the
activation-path floor: it is the compatibility baseline the portable core was
extracted from, and its evidence is the long-standing behavioral hook and
identity suites. Those suites invoke the guards directly with fixtures; they are
contract evidence, not host-runtime activation proof, and no Claude admission
runner exists in this milestone. Codex and Polytoken carry the admission gates.

## Static capability ledger

| Host/profile | Instructions | Skills | Memory | Subagents | Identity hooks | Permissions | Integrations |
|---|---|---|---|---|---|---|---|
| Claude Code/full | native | native | native | native | native | native | adapted |
| Codex/core | native | adapted | unsupported | native | unsupported | native | unsupported |
| Codex/standard/full | native | adapted | adapted | native | adapted | native | unsupported |
| Polytoken/core | native | adapted | unsupported | native | unsupported | native | unsupported |
| Polytoken/standard/full | native | adapted | adapted | native | adapted | native | unsupported |
| Copilot/core preview | adapted | unsupported | unsupported | unsupported | unsupported | not-tested | unsupported |

“Memory adapted” means explicit reads and writes against a configured memory root,
not host auto-loading. Identity-hook support covers the admitted GitHub push and
commit-author guards on local shell tool paths; it is an accident-prevention
rail, not universal containment.

## Artifact admission

- **Shared core:** four portable rules, memory/integration docs, and canonical
  `status`.
- **Shared standard:** memory template and exactly the GitHub identity guard
  files plus one host-event bridge.
- **Codex:** one global instruction adapter, one hook template, and single-file
  `code`, `kickoff`, and `wrap` skills. Skills are linked from the Codex skill
  namespace to managed installed sources.
- **Polytoken:** one global instruction adapter, one hook template, and the same
  three single-file host adapters. Skills are managed copies in Polytoken's
  higher-precedence config directory. Shipped facets/subagents remain untouched.
- **Copilot preview:** one repository instruction and four namespaced rules.

No adapter-local scripts, copied facet/subagent definitions, companion skill
metadata, or Claude adapter tree are admitted. Canonical skill bodies stay in
`skills/`; host-coupled lifecycle behavior stays in thin adapters.

## Explicit exclusions

Codex and Polytoken exclude `push`, NineAngel, `retro`, `wrap-stale`, email,
task, browser, and other integration skills. They do not require Claude Code,
Anthropic, `claude -p`, `ccusage`, or `~/.claude` state. Copilot excludes all
skills, hooks, memory, custom agents, MCP, lifecycle adapters, and global files.

## Admission and change rule

A new artifact or capability is admitted only after all of these land together:

1. a manifest entry and profile allowlist;
2. an existing source path with no duplicate canonical body;
3. deterministic contract/lifecycle tests;
4. accurate host docs and capability status;
5. a host-runtime check when the claim depends on discovery or enforcement.

A skipped or unavailable runtime check records local `unverified`; it cannot
weaken or strengthen static support. Polytoken release readiness additionally
requires fresh machine-bound runtime evidence under the release gate. That gate
is local tamper-evident freshness validation, not cryptographic attestation
against an actor who controls the evidence, executable, and local filesystem.
