# NineAngel

A multi-persona reviewer battery for [Claude Code](https://claude.com/claude-code). Runs your code (or your prompt files, or your install docs) past a panel of independent reviewer personas — each looking for a different class of problem — and synthesizes their findings into a single ranked report.

The premise: a single reviewer (human or LLM) has blind spots. A naive reader, a security adversary, a maintainability-obsessed future-self, and a data-integrity tracer notice different things. Run them in parallel; reconcile after.

## What it looks like

```
$ /angel
Detecting project signals... Skipped fresh, test (no package.json or tests detected).
Running 8 personas in parallel on the current diff...

## Top 5
1. **Critical** `[moderate]` — Adversarial — `auth/login.ts:42` — input concatenated into SQL
2. **Critical** `[trivial]` — Naive / User — `api/users.ts:103` — error swallowed; client sees 200
3. **Important** `[moderate]` — Data-Integrity — `sync/canvas.ts:118` — adapter returns 200 without persisting
4. **Important** `[significant]` — Future-Me — `payments/refund.ts:67` — implicit coupling between modules
5. **Important** `[trivial]` — Hypercritical — `utils/parse.ts:23` — boolean param controls 3 behaviors

Verdict: CHANGES REQUIRED
```

Each persona is an independent subagent. None of them sees the others' findings until the Integrator reconciles them. The Integrator deduplicates, ranks by severity × consensus × effort, and renders a verdict.

## The personas

NineAngel auto-detects which personas are relevant to your project from signals in the file tree (`package.json` → freshness/test fire, `*.sql` → data-integrity fires, `personas/*.md` → coach fires, etc.). Run `/angel` with no arguments to get the auto-detected battery; pass `--all` to bypass detection.

**Default-yes** (run automatically when their triggers match — see `DESIGN.md` for the full signal table):

| Short      | Triggers                              | What it looks for                                                               |
|------------|---------------------------------------|---------------------------------------------------------------------------------|
| `naive`    | always                                | Cold read — unclear naming, dead code, confusing flow                           |
| `adv`      | always                                | Security — injection, auth gaps, race conditions, secret leakage                |
| `hyper`    | always                                | Hypercritical — over-engineering, cargo-cult patterns, lazy abstractions        |
| `thousand` | always                                | Thousand-foot — wrong abstraction level, scope creep, simpler approaches        |
| `future`   | always                                | Future-Me — code clever only today, missing "why" comments, implicit coupling   |
| `user`     | UI / public API / CLI / README        | UX walkthrough — meaningless errors, silent failures, broken flows              |
| `fresh`    | package.json / lockfile / CI config   | Freshness — stale deps, hardcoded URLs/dates, deprecated patterns               |
| `test`     | tests dir / package.json              | Tests — test mocks not behavior, missing edge cases, assertions that can't fail |
| `data-int` | schema / SQL / DB driver dep          | Data-Integrity — FK/NOT-NULL audit, sync-adapter effect verification            |
| `perf`     | runtime code / hot-path indicators    | Performance — O(n²), DB queries in loops, allocation patterns                   |
| `coach`    | prompt files (personas, skills)       | Reviews agent prompts — alignment + execution                                   |

**Opt-in** (named explicitly):

| Short       | What it looks for                                                                           |
|-------------|---------------------------------------------------------------------------------------------|
| `install`   | Tests the soup-to-nuts install flow as a non-developer (runs project commands — opt-in by design) |
| `blindspot` | Finds capabilities, safeguards, or flows entirely absent from the code (full-project only; **experimental**) |
| `penny`     | Cost reviewer — lines, bytes, MB, $, cognitive load, maintenance burden ("rent test"; **experimental**) |

Each persona's frontmatter (`personas/<short>.md`) declares its `default`, `modes`, `experimental` flag, and required signals. The orchestrator reads this at preflight; the frontmatter is the source of truth.

## Usage

```
/angel                        # auto-detected battery on current diff
/angel --full                 # auto-detected battery, whole-project review
/angel naive adv              # only specific personas (bypasses detection)
/angel --all                  # every default-yes persona (ignores signals)
/angel -perf                  # standard battery minus Performance
/angel --loop                 # review → fix → re-review (max 3 cycles)
/angel penny --full           # opt-in persona on the whole project
/angel --multiball=3          # run each persona 3x; integrator reconciles variance (occasional use; ~30+ subagents)
/angel --fix-last             # apply the last review's fix batch in this project
```

If detection would drop more than 2 default personas (or if signals are ambiguous), NineAngel asks before dispatching. Otherwise it proceeds silently with a one-line note.

## Install

NineAngel is a Claude Code skill. To install:

```bash
mkdir -p ~/.claude/skills
git clone https://github.com/PropterMalone/NineAngel.git ~/.claude/skills/angel
```

Restart Claude Code. To verify the install: type `/help` in Claude Code; `/angel` should appear in the listed slash commands. (Or just type `/angel` — if the skill registered, you'll see its description; if not, you'll get "unknown command.")

**Requirements:** Claude Code 2.x or later (`claude --version` to check). Personas dispatch via the Agent tool, so the harness must support sub-agents.

**Platform support:** Linux and macOS. Windows users with Claude Code installed should substitute the install path for the Windows equivalent (`%USERPROFILE%\.claude\skills\angel`); some shell-derived paths in the orchestrator (e.g., `pwd | sed 's|/|-|g'`) assume POSIX shell behavior. Untested on Windows.

## How it works

1. **Battery selection.** The orchestrator scans the project tree for signals (file types, configs, deps) and selects the personas whose triggers match. Named personas bypass detection; `--all` runs everything default-yes.
2. **Pre-flight gate.** Before any persona runs, Claude Code runs the project's tests, build, and linter (if configured). A red gate aborts the review — no point reviewing code that doesn't compile.
3. **Parallel dispatch.** Each selected persona runs as an independent Agent-tool subagent on its own model tier (Haiku / Sonnet / Opus depending on workload). None see the others' findings. The project's CLAUDE.md and diff are wrapped in untrusted-content envelopes so prompt-injection attempts in reviewed code surface as findings rather than altering persona behavior.
4. **Integration.** The Integrator (always Opus) collects raw outputs, sanitizes them, deduplicates cross-persona overlap, ranks by severity × consensus × effort, renders a Top 5, and produces a verdict: APPROVED / APPROVED (with suggestions) / CHANGES RECOMMENDED / CHANGES REQUIRED.
5. **Optional loop.** With `--loop`, fixes are dispatched to a coding subagent and the battery re-runs (max 3 cycles). Line-level findings converge fast; architectural findings ("wrong abstraction") often persist and need human attention.
6. **Per-project handoff.** A handoff file (review summary + ranked findings) and a machine-consumable fix-batch are written to `~/.claude/projects/{encoded-cwd}/memory/`. `/angel --fix-last` (later, in the same project directory) dispatches the fix-batch to a coding subagent.

See `DESIGN.md` for architecture detail.

## Status

Personal tool, used in production by the author. Stable enough to rely on; the persona roster evolves as new failure modes are encountered. Recently-added personas marked `experimental` in their frontmatter (currently `blindspot` and `penny`) are excluded from the auto-battery until they earn their slot — see `DESIGN.md` for graduation criteria.

## License

MIT — see `LICENSE`.
