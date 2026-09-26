# PropterMaltwo

PropterMaltwo is a portable agent-working environment: shared quality doctrine,
testing rules, memory conventions, lifecycle practices, and safety guards with
first-class adapters for **Claude Code, Codex CLI, and Polytoken**. A deliberately
narrow **GitHub Copilot preview** installs repository instructions only.

It began as a genericized snapshot of a real Claude Code setup. Claude remains
the compatibility baseline, but portable content now has one source and each
host gets only the thin adapter it needs. Codex and Polytoken do not use Claude
Code or Anthropic as a hidden backend.

## Why I built it

I built PropterMaltwo to help myself work better with ADHD. Its central job is
to preserve intention and context across interruption, make re-entry cheaper,
and let an agentic harness serve as a universal keyboard across tools that would
otherwise require repeated manual context switching. The portability and safety
engineering followed because this became infrastructure I rely on.

The full first-person account is [Why I built PropterMaltwo: ADHD and agentic
work](docs/adhd-and-agentic-work.md). The companion [connected-work
guide](docs/connected-work.md) covers optional communications, calendar, task,
document, browser, and consent-aware meeting-recording seams. Those connectors
are not implied features of every host profile; the capability table and
integration ledger below remain authoritative.

## Quick start

Clone the repository and dry-run before applying:

```bash
git clone https://github.com/PropterMalone/PropterMaltwo.git
cd PropterMaltwo

# Backward-compatible Claude Code full install
./install.sh
./install.sh --apply

# Primary first-class adapter
./install.sh --host polytoken --profile standard
./install.sh --host polytoken --profile standard --apply
./install.sh --host polytoken --profile standard --doctor

# Codex first-class adapter
./install.sh --host codex --profile standard
./install.sh --host codex --profile standard --apply

# All global first-class hosts; excludes Copilot
./install.sh --host all
./install.sh --host all --apply

# Copilot preview is always explicit and project-scoped
./install.sh --host copilot --profile core --project /path/to/project
./install.sh --host copilot --profile core --project /path/to/project --apply
```

Dry run is the default. Claude accepts only `full`; Codex and Polytoken accept
`core`, `standard`, and `full` (`full` currently equals `standard`); Copilot
accepts only project-scoped `core`. `--host all` accepts no profile or project
and means exactly Claude full + Codex standard + Polytoken standard.

Detailed setup, merge, verification, gaps, and rollback:

- [Claude Code](docs/hosts/claude-code.md)
- [Codex CLI](docs/hosts/codex.md)
- [Polytoken](docs/hosts/polytoken.md)
- [GitHub Copilot preview](docs/hosts/copilot.md)

## Profiles and capabilities

**First-class** means the admitted surface has installer, doctor, rollback,
deterministic contracts, and an actual-host activation path. **Preview** means a
useful bounded surface exists without that full admission floor. Static support
is separate from machine-local activation: installed hooks are not called active
until a runtime check records `verified-active`.

| Host/profile | Instructions | Skills | Memory | Subagents | Identity hooks | Permissions | Integrations |
|---|---|---|---|---|---|---|---|
| Claude Code/full | native | native | native | native | native | native | adapted |
| Codex/core | native | adapted | unsupported | native | unsupported | native | unsupported |
| Codex/standard/full | native | adapted | adapted | native | adapted | native | unsupported |
| Polytoken/core | native | adapted | unsupported | native | unsupported | native | unsupported |
| Polytoken/standard/full | native | adapted | adapted | native | adapted | native | unsupported |
| Copilot/core preview | adapted | unsupported | unsupported | unsupported | unsupported | not-tested | unsupported |

Codex and Polytoken core admit exactly `code,status`; standard/full admit exactly
`code,status,kickoff,wrap`. Memory is explicit-read on those hosts. NineAngel,
`retro`, `wrap-stale`, `push`, and external email/task/browser workflows remain
excluded until each has a tested adapter. See the full
[portability/admission ledger](docs/portability-admission.md).

## Shared core, thin adapters

Portable doctrine stays in `rules/`, the memory convention in `docs/` and
`templates/`, and portable canonical skills in `skills/`. Host-coupled behavior
lives under `adapters/`:

- Codex uses its native instruction chain, Agent Skills, subagent mechanism, and
  user-layer hooks.
- Polytoken uses its instruction chain, managed-copy skills, shipped
  `general-purpose` subagent, and shipped `plan` → `execute` facets. The adapter
  installs no facet or subagent definitions and pins no provider/model.
- Copilot preview receives one repository instruction and four namespaced rules;
  it gets no skills, hooks, agents, MCP, or memory.

The installer tracks managed checksums, ownership, backups, and transactions.
Conflicting new-host instruction/config files are staged as
`.proptermaltwo.example` fragments rather than overwritten. Uninstall removes
only unchanged managed content and preserves shared assets still owned by
another host.

## What the environment contains

### Doctrine

`rules/quality.md`, `rules/testing.md`, `rules/glossary.md`, and `rules/comms.md`
cover calibration and falsifiability, test discipline, shared terminology, and
project-scoped communications. Host instruction adapters point to these files;
they do not duplicate the text.

### Memory and lifecycle

The [memory system](docs/memory-system.md) uses a hot `MEMORY.md`, optional cold
`roster.md`/`topics.md`, typed topic files, calibration, and concise handoffs.
Claude can auto-load its memory tree. Codex and Polytoken require an explicit
memory root in project instructions or `PROPTERMALTWO_MEMORY_DIR`; their thin
`kickoff` and `wrap` adapters never infer `~/.claude` state.

### Skills

Claude retains the complete existing skill collection. The new first-class
adapters deliberately admit a smaller tested set:

- `code`: bounded host-native delegation with structured completion;
- `status`: canonical one-shot background-work view;
- `kickoff`: bounded explicit-memory orientation;
- `wrap`: durable handoff/memory closeout with no automatic commit or push.

The remaining skills include the NineAngel review battery, retro, workflow
helpers, and integration examples. They are not implied portable merely because
the source exists.

### Safety hooks

The standard Codex and Polytoken profiles install exactly two translated
pre-shell guards: GitHub push identity and commit-author identity. Both invoke
one shared bridge and the canonical guard policies. Hook coverage is limited to
the host's local shell tool path and remains an accident-prevention rail, not an
adversary-proof sandbox. See each host page for trust/reload and activation
requirements.

### Optional integrations

Email, Google Workspace, task managers, browser handoff, notifications, MCP, and
cross-model review require tools and credentials you supply. They are seams, not
hidden dependencies. [Integrations](docs/integrations.md) names the host/tool
requirements and support status.

## Make it yours

1. Choose one host page and apply its profile in an isolated or disposable home
   first.
2. Run `--doctor`; resolve staged instruction/hook fragments.
3. For Codex or Polytoken standard, configure an explicit memory root and reload
   skills/hooks.
4. Exercise runtime discovery and the hook allow/deny fixtures before relying on
   them.
5. Wire only the optional integrations you actually use.

Decision records use falsifiable ADRs; see
[docs/decision-records.md](docs/decision-records.md). The portability architecture
is recorded in
[ADR 01](docs/decisions/01-portable-core-thin-host-adapters.md).

## License

MIT. NineAngel under `skills/angel/` carries its own MIT license (same terms).
