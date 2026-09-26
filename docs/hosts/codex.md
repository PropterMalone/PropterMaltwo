# Codex CLI host setup

Codex CLI is a **first-class** PropterMaltwo host. `core` provides instructions,
portable doctrine, `code`, and `status`; `standard` adds explicit-read memory,
`kickoff`, `wrap`, and GitHub identity hooks. `full` currently equals
`standard` artifact for artifact.

## Prerequisites and install

- A current Codex CLI installation and authentication.
- Python 3 for the shared hook bridge in `standard`/`full`.
- Optional overrides: `CODEX_HOME`, `CODEX_SKILLS_HOME`, and
  `PROPTERMALTWO_HOME`.

```bash
./install.sh --host codex --profile core
./install.sh --host codex --profile standard --apply
./install.sh --host codex --profile standard --doctor
```

Defaults are `$CODEX_HOME=~/.codex`, `$CODEX_SKILLS_HOME=~/.agents/skills`, and
`$PROPTERMALTWO_HOME=${XDG_DATA_HOME:-~/.local/share}/proptermaltwo`.

## Installed paths and merge points

- `$CODEX_HOME/AGENTS.md` (or `AGENTS.md.proptermaltwo.example` on conflict).
- Managed adapter copies under `$PROPTERMALTWO_HOME/adapters/codex/skills/`.
- Conflict-safe skill links under `$CODEX_SKILLS_HOME`.
- `$CODEX_HOME/hooks.json` for standard/full. Existing valid JSON keeps all
  unrelated handlers. Inline TOML hooks, invalid JSON, semantic ambiguity, or a
  same-bridge/different-definition conflict leaves config unchanged and stages
  `$CODEX_HOME/hooks.proptermaltwo.example.json`.

If a fragment is staged, merge it manually, enable hooks if your Codex version
requires that feature flag, restart Codex, inspect startup warnings, and review
or trust the definitions through `/hooks`. The bridge defaults the guards to the
sibling `$PROPTERMALTWO_HOME/shared/hooks/github-identity-map.json`; only
`github-identity-map.example.json` is seeded, so copy and edit it (or set
`PROPTERMALTWO_GH_IDENTITY_MAP`) before publication. Codex does not consult
`~/.claude` for the map by default.

## Verify

```bash
./install.sh --host codex --profile standard --doctor
```

For a local `verified-active` claim, use `scripts/codex_admission.py` against a
fully installed isolated `CODEX_HOME`, isolated skills home, and disposable Git
working tree. The runner binds evidence to the installed instruction, skills,
hook configuration, bridge, guards, host version, and machine. It parses Codex
JSONL plus rollout records and verifies filesystem sentinels; model prose cannot
produce a pass.

The runner never uses `--dangerously-bypass-hook-trust`. A fresh non-managed
hook definition normally yields `installed-untrusted`: instruction and skill
discovery and benign Bash may pass, but the push-shaped fixture executes because
the exact hook hash has not been trusted. Open `/hooks` in interactive Codex,
review and trust the two definitions, restart, remove probe sentinels, and rerun
the same admission command. Only a normal no-bypass runtime denial before the
side-effect marker permits `verified-active` evidence.

The default probe sandbox is `workspace-write`. Some Linux hosts prohibit the
bubblewrap user/network namespace setup Codex needs; that is recorded as
`failed`, not silently downgraded. For a disposable, local-only fixture tree you
may explicitly pass `--sandbox danger-full-access`. This choice is recorded in
the evidence and is never selected as an automatic fallback. Hook installation
alone is not active.

After applying `standard` into isolated paths, run the harness with every path
spelled out; repeat `--skill-path` in `code,status,kickoff,wrap` order:

```bash
python3 scripts/codex_admission.py \
  --isolated-home "$ISO/home" --codex-home "$ISO/codex" \
  --skills-home "$ISO/home/.agents/skills" --working-dir "$ISO/work" \
  --evidence "$ISO/evidence/codex-evidence-v1.json" \
  --activation "$ISO/data/proptermaltwo/state/activation-v1.json" \
  --config "$ISO/codex/hooks.json" --instruction "$ISO/codex/AGENTS.md" \
  --hook-template adapters/codex/hooks.json.tmpl \
  --bridge "$ISO/data/proptermaltwo/shared/hooks/host-hook-bridge.py" \
  --push-guard "$ISO/data/proptermaltwo/shared/hooks/gh-identity-guard.py" \
  --commit-guard "$ISO/data/proptermaltwo/shared/hooks/gh-commit-author-guard.py" \
  --skill-path "$ISO/home/.agents/skills/code/SKILL.md" \
  --skill-path "$ISO/home/.agents/skills/status/SKILL.md" \
  --skill-path "$ISO/home/.agents/skills/kickoff/SKILL.md" \
  --skill-path "$ISO/home/.agents/skills/wrap/SKILL.md"
```

## Memory and lifecycle

Codex does not auto-load PropterMaltwo memory. Set `PROPTERMALTWO_MEMORY_DIR` or
name a memory root in project `AGENTS.md`. `kickoff` and `wrap` read/write only
that explicit root. They do not use Claude transcripts, `claude -p`, Anthropic,
or `~/.claude` state. `wrap` does not automatically commit or push.

## Known gaps and integrations

Only `code`, `status`, `kickoff`, and `wrap` are admitted in standard/full.
NineAngel, retro, stale-wrap, push, email, task, browser, and other integration
skills are excluded. The two identity hooks intercept Codex `Bash` tool calls;
hosted or opt-out tool paths remain outside this guardrail. See
[Integrations](../integrations.md) before wiring optional external tools.

## Rollback and uninstall

```bash
./install.sh --host codex --profile standard --uninstall
./install.sh --host codex --profile standard --uninstall --apply
```

Uninstall removes only unchanged managed files/links/definitions and retains
shared content still owned by another host. Modified files survive with a
warning. Doctor prints recovery steps for an unresolved transaction journal.
