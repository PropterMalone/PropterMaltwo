# Project Setup Checklist

The checklist a new project runs through before the first feature. CLAUDE.md's Session Management
section points here.

The stack below is one worked example (TypeScript + Vitest + Biome). The *order* is the portable
part: language before terminology gets you a codebase whose nouns nobody agreed on.

## Phase 0 — Domain Language

- [ ] Read `~/.claude/rules/glossary.md`; use shared terms unchanged where they fit
- [ ] Create `docs/glossary.md` for project-specific terms and explicit refinements only
- [ ] Give each load-bearing entry a definition, a `Not` boundary, and an invariant or observable
      consequence when one exists
- [ ] Resolve or record terminology conflicts before architecture makes the choice implicitly
- [ ] When a local term appears in a second project, promote its common meaning to the shared
      glossary and replace local copies with pointers or refinements

## Decision records

- [ ] Create `docs/decisions/` and copy `templates/adr-template.md` as the shape
- [ ] Skim the cross-project "house" decision set (if you keep one) before deciding anything a
      previous project already decided — see [`docs/decision-records.md`](docs/decision-records.md)
- [ ] If the project ships a weekly falsifier sweep, confirm `docs/decisions/` is on its root list
      (`ADR_SWEEP_PROJECTS` / `ADR_SWEEP_EXTRA_ROOTS`, see `scripts/adr-sweep.py`)

## Repository

- [ ] Initialize version control (`jj git init` or `git init`)
- [ ] Create main branch/bookmark
- [ ] Add .gitignore (include `.env`, `node_modules/`, `dist/`, `coverage/`, `*.tsbuildinfo`)
- [ ] Create `.env.example` with required vars

**Note:** Jujutsu (jj) is preferred here and works against git repositories, so the rest of this
file assumes either. If you use plain git, skip the jj-only steps under Local Quality Checks.

## TypeScript

- [ ] `npm init -y`
- [ ] `npm i -D typescript @types/node`
- [ ] Create tsconfig.json with strict: true

## Testing

- [ ] `npm i -D vitest @vitest/coverage-v8 happy-dom`
- [ ] Configure coverage thresholds (95% minimum)
      <!-- adapt: 95% is this setup's bar and it only works because `rules/testing.md` says not to
           chase coverage on UI glue. Pick a number you will actually enforce; an unenforced
           threshold is worse than none, because CI green stops meaning anything. -->
- [ ] Add `--passWithNoTests` to the vitest config so a fresh repo's validate chain still runs
- [ ] Add test scripts to package.json

## Linting & Formatting (Biome)

- [ ] `npm i -D --save-exact @biomejs/biome`
- [ ] `npx biome init` (creates `biome.json`)
- [ ] Configure biome.json. The `$schema` URL embeds the CLI version, so it must match the version
      you just installed:
  ```json
  {
    "$schema": "https://biomejs.dev/schemas/2.4.15/schema.json",
    "assist": {
      "actions": {
        "source": {
          "organizeImports": "on"
        }
      }
    },
    "formatter": {
      "indentStyle": "tab",
      "lineWidth": 100
    },
    "linter": {
      "enabled": true,
      "rules": { "recommended": true }
    }
  }
  ```
  <!-- adapt: 2.4.15 is a worked example, not a pin to copy. Run `npx biome --version` and use
       that. The three notes below are the biome 1.x → 2.x migration traps; they cost real
       debugging time each, which is why they are written down rather than rediscovered. -->
  Notes on biome 2.x changes from older templates:
  - `$schema` URL embeds the CLI version; mismatch → "schema version does not match" error.
  - `organizeImports` (top-level) → `assist.actions.source.organizeImports: "on"`.
  - `files.ignore` → `files.includes` (negated patterns) — usually unneeded; `.gitignore` is
    respected by default.
- [ ] Add scripts to package.json:
  ```json
  {
    "format": "biome format --write .",
    "lint": "biome lint .",
    "check": "biome check --write .",
    "validate": "biome check --write . && tsc -b && vitest run --coverage"
  }
  ```

**Note:** Existing projects on another linter/formatter don't need to migrate. Use Biome for new
projects only.

## Dead-code gate

- [ ] From the project root, run `~/.claude/scripts/setup-knip-fallow.sh`
- [ ] Confirm `npm run validate` now ends in `npm run lint:dead`

CLAUDE.md's Tech Stack section names this gate as part of `validate`. It is idempotent, so re-run
it on an existing project to wire the gate in after the fact.

## Local Quality Checks

### jj projects (preferred)

- [ ] Configure `jj fix` with biome:
  ```toml
  # .jj/repo/config.toml or ~/.jjconfig.toml
  [fix.tools.biome]
  command = ["npx", "biome", "check", "--write", "--stdin-file-path=$path"]
  patterns = ["glob:'**/*.ts'", "glob:'**/*.tsx'", "glob:'**/*.js'", "glob:'**/*.css'"]
  ```
- [ ] Create a push alias that runs validate first: `alias jjp='npm run validate && jj git push'`

### git projects (or jj colocated)

- [ ] `npm i -D husky lint-staged`
- [ ] `npx husky init`
- [ ] Configure pre-commit: `npx biome check --write --staged`
- [ ] Configure pre-push: test

## CI

<!-- adapt: GitHub Actions here; any CI works. The requirement is that the same command the
     pre-push hook runs is the command CI runs, so "passes locally" and "passes in CI" cannot
     drift apart. -->

- [ ] Create `.github/workflows/pr.yml`
- [ ] Run: `biome ci .` + `tsc --noEmit` + `vitest run --coverage`
- [ ] Require passing checks for merge
- [ ] Enforce coverage threshold

## Dependencies

- [ ] Enable Dependabot or Renovate for auto-updates
- [ ] Commit package-lock.json

## Documentation

- [ ] Project instructions (`AGENTS.md` and/or `CLAUDE.md`) cover stack, commands, architecture, and
      conventions
- [ ] Every project agent-instruction file points to `docs/glossary.md`
- [ ] README only if the project will be public or shared
