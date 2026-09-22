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

Each persona is an independent subagent. None sees the others' findings. A bounded semantic reducer later receives only a mechanically derived JSON workset, returns schema-constrained decisions, and a deterministic renderer produces the report and verdict.

## The personas

NineAngel auto-detects which personas are relevant to your project from signals in the file tree (`package.json` → freshness/test fire, `*.sql` → data-integrity fires, `personas/*.md` → coach fires, etc.). Run `/angel` with no arguments to get the auto-detected battery; pass `--all` to bypass detection.

**Default-yes** (run automatically when their triggers match — see `DESIGN.md` for the full signal table):

| Short      | Triggers                              | What it looks for                                                               |
|------------|---------------------------------------|---------------------------------------------------------------------------------|
| `naive`    | always                                | Cold read — unclear naming, dead code, confusing flow                           |
| `adv`      | always                                | Security — injection, auth gaps, race conditions, secret leakage                |
| `hyper`    | always                                | Hypercritical — over-engineering, cargo-cult patterns, lazy abstractions        |
| `blindspot`| always (full-project mode only)       | Finds capabilities, safeguards, states, or flows entirely absent from the code  |
| `future`   | always                                | Future-Me — code clever only today, missing "why" comments, implicit coupling   |
| `rtfm`     | always                                | Checks code against authoritative docs — spec violations, unused doc'd APIs     |
| `user`     | UI / public API / CLI                 | UX walkthrough — meaningless errors, silent failures, broken flows              |
| `test`     | tests dir                             | Tests — test mocks not behavior, missing edge cases, assertions that can't fail |
| `data-int` | schema / SQL / DB driver dep          | Data-Integrity — FK/NOT-NULL audit, sync-adapter effect verification            |
| `perf`     | hot-path indicators                   | Performance — O(n²), DB queries in loops, allocation patterns                   |
| `coach`    | prompt files (personas, skills)       | Reviews agent prompts — alignment + execution                                   |
| `editor`   | prose artifacts                       | Prose quality — clarity, structure, tone, wasted words in docs/READMEs/ADRs    |
| `rigor`    | prose artifacts                       | Analytical rigour — unsupported claims, vague hedges, missing falsifiers        |
| `orgpolicy` | Governed client work (`organization_policy_project`) | Domain angel — reviews against an **organization's written policy**, not craft: data isolation, delivery channel, engagement posture, attribution |

`orgpolicy` is the one default-yes persona whose signal is **not** bypassed by `--all` / `PERSONAS: all`, and the only one skipped rather than dispatched when its external policy registry does not resolve. A policy reviewer improvising rules carries authority that does not exist, so running it blind is worse than not running it. See ADR-15.

**Opt-in** (named explicitly):

| Short       | What it looks for                                                                           |
|-------------|---------------------------------------------------------------------------------------------|
| `install`   | Tests the soup-to-nuts install flow as a non-developer (runs project commands — opt-in by design) |
| `thousand`  | Thousand-foot — wrong abstraction level, scope creep, simpler approaches (opt-in since the 2026-06-06 Blindspot↔Thousand swap) |
| `fresh`     | Freshness — stale deps, hardcoded URLs/dates, deprecated patterns (demoted ADR-07) |
| `heir`      | Cold-start handoff audit — can a never-met operator + AI agent use/understand/troubleshoot/modify this? (**experimental**) |
| `recip`     | Recipient — reads the **rendered artifact**, not the source: did the reader get what they came for? (**experimental**; full-mode only; needs `--artifact <path>`) |
| `penny`     | Cost reviewer — lines, bytes, MB, $, cognitive load, maintenance burden ("rent test"; **experimental**) |
| `pii`       | Raw-PII detector — personal data in logs, fixtures, dumps, serializers (**experimental**; runs first in the privacy pair) |
| `deanon`    | Re-identification attacker — quasi-identifiers, reversible pseudonyms, linkage (**experimental**; always runs after `pii`) |

Each persona's frontmatter (`personas/<short>.md`) declares its `default`, `modes`, `experimental` flag, and required signals. The orchestrator reads this at preflight; the frontmatter is the source of truth.

Experimental personas (`penny`, `pii`, `deanon`, `heir`, `recip`) are excluded from auto-battery until they earn their slot — see `DESIGN.md` for graduation criteria.

`recip` is the one persona that reviews **output** rather than source, so it needs the output handed to it:

```
/angel recip --full --artifact ./out/report.md    # review what the system emits
```

It is full-mode only: a diff never contains the artifact, so there is nothing for it to read in diff mode. To judge whether a change improved the output, run it against the artifact produced before and after.

Without `--artifact` it looks for committed outputs (`examples/`, `fixtures/`, `samples/`, snapshots) and asks before using them. It never runs blind, and unattended runs skip it with a recorded reason rather than generating an artifact by executing project code.

## Usage

```
/angel                        # auto-detected battery on current diff
/angel --full                 # auto-detected battery, whole-project review
/angel naive adv              # only specific personas (bypasses detection)
/angel --all                  # every default-yes persona (ignores signals)
/angel --micro                # minimal-core profile: adv+hyper+data-int (if signaled)
/angel -perf                  # standard battery minus Performance
/angel --loop                 # review → fix → re-review (max 3 cycles)
/angel penny --full           # opt-in persona on the whole project
/angel --multiball[=N]        # default-ON interactive at N=2 (N=3 on --full/--all); pass =N to override; integrator reconciles
/angel --balls N              # explicit multiball pass-count override (alias for --multiball=N)
/angel --no-multiball         # force single-pass (off-switch; alias: --single)
/angel --cross                # cross-model second opinion (default-ON for interactive; --no-cross to suppress)
/angel --no-cross             # suppress the default cross-model leg (§5.6)
/angel --no-verify            # skip the adversarial verification stage (§5.7; default ON when verify_queue is non-empty)
/angel --model-override <tier># force all personas to one tier (sonnet|opus|fable; haiku retired by ADR-21); integrator unaffected (SKILL.md §5)
/angel --reader               # enable the Bundle Reader (default-off per ADR-01 — no reliable advantage)
/angel --fix-last             # apply the last review's fix batch in this project
/angel <project-name>         # cd into the named project, then review it
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

**Platform support:** Linux and macOS for the review battery. Semantic integration additionally requires the exact supported Codex CLI release, signed in with ChatGPT, plus a successful local runner qualification. The reducer uses the ChatGPT/Codex subscription allowance; it never uses an OpenAI API key. A Codex upgrade deliberately invalidates admission until NineAngel supports that release and the probe is rerun. Set `ANGEL_REDUCER_BACKEND=disabled` to force the visible deterministic-union fallback. Windows users with Claude Code installed should substitute the install path for the Windows equivalent (`%USERPROFILE%\.claude\skills\angel`); some shell-derived paths in the orchestrator (e.g., `pwd | sed 's|/|-|g'`) assume POSIX shell behavior. Untested on Windows.

## How it works

1. **Battery selection.** The orchestrator scans the project tree for signals (file types, configs, deps) and selects the personas whose triggers match. Named personas bypass detection; `--all` runs everything default-yes.
2. **Pre-flight gate.** Before any persona runs, Claude Code runs the project's tests, build, and linter (if configured). A red gate aborts the review — no point reviewing code that doesn't compile.
3. **Parallel dispatch.** Each selected persona runs as an independent Agent-tool subagent on its own model tier (Sonnet / Opus depending on workload; Haiku retired by ADR-21). None see the others' findings. The project's CLAUDE.md and diff are wrapped in untrusted-content envelopes so prompt-injection attempts in reviewed code surface as findings rather than altering persona behavior.
4. **Integration.** Scripts parse the durable Markdown into a lossless, lineage-bearing workset. A qualified, fail-closed Codex process authenticated through ChatGPT makes only semantic merge/rank decisions. The exact CLI binary is pinned and content-bound; hosted web search and local execution hosts are disabled before inference; the mandate is a developer instruction while the nonce-delimited workset is untrusted user data; and emitted events are audited. Deterministic code validates total candidate accounting and renders both report and snapshot. Oversized inputs are sharded below a 24k estimated-input cap. If qualification or the reducer is unavailable, every candidate remains visible in an explicitly degraded deterministic-union report—there is no inline synthesis fallback (ADR-20).
5. **Optional loop.** With `--loop`, fixes are dispatched to a coding subagent and the battery re-runs (max 3 cycles). Line-level findings converge fast; architectural findings ("wrong abstraction") often persist and need human attention.
6. **Per-project handoff.** A handoff file (review summary + ranked findings) and a machine-consumable fix-batch are written to `~/.claude/projects/{encoded-cwd}/memory/`. `/angel --fix-last` (later, in the same project directory) dispatches the fix-batch to a coding subagent.

See `DESIGN.md` for architecture detail.

## Unattended / scheduled reviews

For `claude -p` runs (job queues, scheduled audits) use `unattended.md` instead of the interactive skill — same battery-selection logic, but it never asks questions and treats a failed pre-flight as a hard stop. Queue prompts reference it directly:

```
Read ~/.claude/skills/angel/unattended.md and follow it exactly.
PROJECT_DIR: ~/Projects/{project}
```

Optional inputs: `PERSONAS: <comma-separated list>` (override detection), `MODE: diff | full` (default `full`), `REPORT_PATH`, `MODEL_OVERRIDE`, `RUN_TAG` — see `unattended.md`'s Inputs section.

## Scripts

Support tooling in `scripts/` (each script's header docstring is authoritative):

- `mine-runs.py` — cross-run analytics: per-persona value table (does each persona earn its slot?) and portfolio summary + Critical-findings ledger. `mine-runs.py [--runs-dir DIR] [--since YYYY-MM-DD] [--json]`
- `check-run-complete.py` — verifies a run dir persisted its artifacts (snapshot, usage.json, findings/, usage.log line). `check-run-complete.py <run_dir>` (exit 0/1) or `--all` to audit history.
- `record-disposition.py` — upserts a per-finding disposition (`accepted` … `rejected-wrong`) into `<run_dir>/dispositions.json`; the precision signal mine-runs.py consumes. `record-disposition.py <run_dir> <finding_id> <disposition> [note]`
- `recurrence-pilot.py` — cross-run finding-recurrence pilot: a no-new-logging outcome proxy; observed recurrence is materially stochastic and should be interpreted qualitatively.
- `validate-personas.py` — drift guard: diffs `personas/*.md` against the SKILL.md §1 and unattended.md Step 3 model tables; exits nonzero on drift.
- `init-run.sh` / `record-dispatch.sh` / `aggregate-usage.py` / `finalize-run.sh` — the run-lifecycle mechanisms: `init-run.sh` creates the run substrate (`eval "$(init-run.sh [PROJECT_DIR])"` sets `RUN_DIR`/`ENCODED_CWD`/`HANDOFF_DIR`); `record-dispatch.sh` appends each dispatch's `usage.jsonl` line and findings file; `aggregate-usage.py` rolls `usage.jsonl` into `usage.json`; `finalize-run.sh <RUN_DIR> [RUN_TAG]` is the single end-of-run gate (assemble-wpr → aggregate → completeness gate → usage.log append → dispositions skeleton; ADR-12 — the append is deliberately AFTER the gate, so a gate failure suppresses the line instead of duplicating it).
- `record-run-meta.py` / `integrate-run.sh` — complete reducer-era metadata, then run the bounded build → isolated semantic reduction → validation → deterministic rendering → finalization pipeline. `probe-integration-runner.sh` qualifies the exact ChatGPT-authenticated Codex installation and its no-tools boundary before semantic use.
- `score-jev-reconciliation.py` / `jev-reconciliation-eval.py` — ADR-22's disclosure-gated, shadow-only duplicate scorer and private evidence workflow. The evaluator pre-registers five blind calibration runs, freezes a threshold, registers ten consecutive holdouts, runs isolated alternate reducers, prepares score-blind adjudication, and evaluates all five promotion clauses. It refuses to write private results inside any git repository.
- `append-usage-log.sh` — internal: generates the canonical usage.log line; called by `finalize-run.sh`, never hand-formatted.
- `finalize-calibration.py` — internal/retired: paired baseline+reader A/B markers for the concluded reader calibration (ADR-01).
- `test_scripts.sh` — smoke tests pinning the script contracts. Run `bash scripts/test_scripts.sh`.

## External dependencies

NineAngel has a few out-of-repo dependencies. Missing ones degrade gracefully (the run continues with a note), except `python3` and `bash` which are hard requirements.

| Dependency | Used by | If absent |
|---|---|---|
| `bash`, `git`, `python3`, `jq` | core scripts (`init-run.sh`, `finalize-run.sh`, `record-dispatch.sh`) | hard failure — required |
| Exact supported Codex CLI release, signed in with ChatGPT and locally qualified | tool-disabled structured-output reducer (ADR-20) | deterministic-union report with `no-qualified-runner` banner; API-key auth is rejected, the child receives only an auth/TLS/proxy environment allowlist, and CLI upgrades require code support plus requalification |
| `~/.claude/skills/jev/scripts/jev-client.mjs` | ADR-22 eligible N=2 shadows only | shadow scoring stops before an artifact is written; Sonnet acting reconciliation is unchanged |
| `~/.claude/scripts/xreview.py` | cross-model leg (§5.6, default-ON interactive) | run logs `cross: failed (xreview.py not found)` — leg skipped, review continues |
| backends `agy` / `codex` | xreview.py routing | xreview.py handles its own backend routing; a missing backend logs `cross: failed ({reason})` |
| `/code` skill (Claude Code) | `--fix-last` and `--loop` fix dispatch | fallback: dispatch any coding subagent with the same preamble from `angel-fix-batch.md`; the fix-batch file is always written and human-readable |

**Fresh-clone check**: after cloning, run `bash scripts/test_scripts.sh` to verify the core scripts work. The cross leg and fix-dispatch rely on out-of-repo tools that the test suite does not exercise — confirm `xreview.py` exists and the `/code` skill is available before relying on those features.

## Status

The review battery is operational. Semantic integration is admitted only after the host-specific probe succeeds and otherwise degrades visibly to a bounded report plus a lossless machine ledger. Personas marked `experimental` in their frontmatter are excluded from the auto-battery until they satisfy the documented qualification criteria.

## License

MIT — see `LICENSE`.
