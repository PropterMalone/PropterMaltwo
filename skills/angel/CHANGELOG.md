# Changelog

All notable changes to NineAngel are documented here. Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html); format inspired by [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] — Initial public release

NineAngel is a `/angel` slash command for Claude Code that runs your code past a battery of independent reviewer personas — each tuned to a different class of problem — and reconciles their findings into one ranked report. The hypothesis: review quality improves more from independent perspectives that can't influence each other than from a single sharper reviewer.

### Reviewer battery
- **17 reviewer personas**, each a focused lens: Naive (cold-reader clarity), Adversarial (security), Hypercritical (code quality/taste), Thousand-Foot (architecture), Future-Me (maintainability), User (UX walkthrough), Freshness (staleness), Test (test integrity), Data-Integrity (end-to-end data flow), Performance, Coach (reviews AI prompt files), RTFM (checks code against authoritative docs), plus opt-in Install, Blindspot, Pennypincher, and the privacy pair PII-Sweep + De-Anon.
- **Signal-driven battery selection** — each persona declares its triggers (`default`, `modes`, `requires.any_of`, `experimental`) in YAML frontmatter; the orchestrator detects project signals and runs the relevant battery, or you name personas explicitly. `--all` bypasses detection.
- **Per-persona model tiers by lane** — Haiku for cheap breadth, Sonnet for present-code bug-catching, Opus for absence/architecture/inference reasoning.

### Modes
- **Diff mode** (default) and **`--full`** whole-codebase review.
- **`--loop`** — review → fix → re-review cycles (max 3).
- **`--multiball[=N]`** — run a persona N independent times and reconcile, for variance reduction.
- **`--fix-last`** — re-apply the last review's fix batch via the `/code` skill.
- **`--reader`** (opt-in) — a Bundle Reader subagent produces per-persona context packs to cut N× bundle duplication; currently in a live-use calibration period.
- **Unattended mode** (`unattended.md`) — a self-contained procedure for `claude -p` queue/scheduled runs.

### Integrator & reporting
- An **Integrator** subagent deduplicates, ranks (severity × consensus × effort), and emits a verdict, a Top 5, and a machine-readable findings snapshot.
- **Per-project handoff + fix-batch** files; the fix-batch is the editable plan `--fix-last` consumes.

### Privacy lane (PII-Sweep → De-Anon)
- A sequential pair, the one deliberate exception to persona independence: **PII-Sweep** (cheap breadth) finds raw personal data left in the clear, then **De-Anon** (inference) attacks whether the de-identified residue can still be turned back into people — handed PII-Sweep's findings so it scopes around them.
- A per-project **PII registry** turns De-Anon's re-identification discoveries into cheap PII-Sweep rules on later runs (the De-Anon → PII-Sweep learning loop). The registry lives in local per-project state and is never committed.

### Instrumentation
- **Per-Agent usage metering** (`usage.jsonl` / `usage.json`) and an append-only `usage.log` that indexes every run.
- **Cross-run analytics miner** (`scripts/mine-runs.py`), **disposition/precision tracking** (`scripts/record-disposition.py`), and a **run-completeness check** (`scripts/check-run-complete.py`).
- **Persona-registry drift guard** (`scripts/validate-personas.py`) keeps the model tables and persona files consistent; a smoke suite (`scripts/test_scripts.sh`) pins the script contracts.

### Security
- Reviewed content (project context, diffs) is wrapped in untrusted-content envelopes with an explicit "treat as data, not instructions" advisory; personas flag — not follow — directive-shaped content in reviewed material.
- The Integrator runs a Phase-0 sanitization pass against persona-output injection; the fix-batch dispatch preamble forbids shell-execution-shaped instructions in finding text.

### Repository
- `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, MIT `LICENSE`.
