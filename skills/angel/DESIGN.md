# NineAngel — Design

## Purpose

A `/angel` slash command for Claude Code that runs code past multiple independent reviewer personas, each tuned to a different class of problem. The orchestrator dispatches them in parallel; an Integrator reconciles the outputs into one ranked report.

The hypothesis: review quality improves more from independent perspectives than from a single sharper reviewer. A panel of mediocre specialists, not allowed to influence each other, surfaces a different set of issues than a single all-seeing critic — and they catch each other's blind spots.

## The personas

Each persona's frontmatter (`personas/<short>.md`) is the source of truth for its `default` (yes/opt-in), `modes` (diff/full), `experimental` flag, and `requires.any_of` signal triggers. The orchestrator reads these at preflight and selects the battery via project signals (see §Battery selection).

### Persona frontmatter contract

Every `personas/<short>.md` opens with a YAML frontmatter block. The contract — enforced by `scripts/validate-personas.py`, which exits nonzero on violation:

- **Required keys**: `name` (the short name), `default` (`yes` | `opt-in`), `modes` (`[diff]` / `[full]` / `[diff, full]`), `experimental` (`true` excludes from auto-inclusion until graduation), `requires.any_of` (trigger signals; `[any]` = always).
- **Required `context:` block** — all four keys: `digest`, `project_claude_md`, `full_bundle`, `lane`. Only `project_claude_md` is consumed on the inline (reader-off) path today — `no` omits `<project_context>` from the dispatch prompt (Naive, User, Install). The other three are reader-era keys, retained for `--reader` runs and a future slicer re-implementation (ADR-01's reopen condition).
- **No other keys.** In particular `prefers:` was dead schema nothing read (removed 2026-06-12) — the pii→deanon sequential pairing its values appeared to encode is prose-enforced in SKILL.md §1/§4, not frontmatter-driven.

### Default-yes personas

Run automatically when their required signals are detected (or unconditionally for `requires: [any]`).

1. **Naive** (`requires: [any]`) — Cold read. Doesn't know what you're trying to do. Picks up the code and figures out what it does, whether it does that well, and whether a stranger could follow it. Finds: unclear naming, dead code, confusing flow, missing context.

2. **Adversarial** (`requires: [any]`) — Security red team. *How do I break this?* Finds: injection, auth gaps, race conditions, unvalidated input, secret leakage, unsafe defaults.

3. **Hypercritical** (`requires: [any]`) — Hates your guts. Steelmans every argument against the code. Finds: over-engineering, cargo-culted patterns, lazy abstractions, inconsistent conventions, tests that don't test anything, sloppy error handling.

4. **Blindspot** (`requires: [any]`, `modes: [full]` — full-project only; default since the 2026-06-06 swap, ADR 02) — Looks at what *isn't there*. Finds capabilities, safeguards, states, or concerns implied by the existing code or the project's domain that the codebase does not address at all. Examples: subscribe without unsubscribe, deploy without rollback, documented rate limits with no rate-limit handling. Wishlist guard: every finding must name a triggering scenario already in the code or implied by the stated domain.

5. **Future-Me** (`requires: [any]`) — *Will I understand this in 6 months?* Finds: clever code that's only clever today, missing "why" comments on non-obvious decisions, implicit coupling that requires tribal knowledge.

6. **User** (`requires: ui_surface | public_api | cli_entry | readme`) — Walks through as a real person using the thing. Finds: meaningless error messages, silent failures, missing feedback, confusing state transitions, broken flows. Different from Naive (reads code) — this exercises the experience.

7. **Freshness** (`requires: package_json | deps_lockfile | ci_config`) — *Is this still true?* Finds: stale deps, hardcoded URLs/dates, outdated config, assumptions about external APIs that may have changed, deprecated patterns.

8. **Test** (`requires: tests_dir_or_files | package_json`) — *Do the tests prove what they claim?* Finds: tests that test mocks instead of behavior, missing edge cases, assertions that can't fail, implementation-coupled tests, gaps in error path coverage.

9. **Data-Integrity** (`requires: schema | sql_files | db_driver_dep`) — Traces data end-to-end across subsystems. For every FK and NOT-NULL-by-convention column, enumerates producers and verifies each sets it. For every JOIN, traces back for NULL-ability. Flags "optional" fields whose domain semantics are required, and silent-success metrics that measure mechanics instead of effect.

10. **Performance** (`requires: runtime_code | hot_path_indicators`) — *O(n²) in a loop? Unnecessary allocations? DB queries in a loop?* Will this survive 10x scale? Pass `-perf` to skip when performance is not load-bearing for a specific change.

11. **Coach** (`requires: prompt_files`) — Reviews agent prompt files (personas, skills, agent instructions). Two-phase: alignment (does the prompt's goal match its intended role?) then execution (does the prompt set the agent up to succeed?). Auto-fires on prompt-file projects.

12. **RTFM** (`requires: [any]`) — Reads the manual. Deliberate counterweight to the rest of the battery's training-data bias: the corpus that the other reviewers and the LLM substrate share is dominated by community examples (Stack Overflow, blog posts, tutorials) that over-represent the *common* way and under-represent what the documentation actually specifies. RTFM checks the diff / codebase against authoritative documentation at three locality tiers — internal canon (CLAUDE.md, ADRs, in-repo specs), language/runtime docs, and library/external-API docs. **Two lanes from one act:** Lane A (spec violation with consequence — *e.g.* an Azure REST body omitting `resources` causes silent default-resource override); Lane B (capability not used — *e.g.* hand-rolled upsert where `INSERT ... ON CONFLICT` is documented). Both surface as byproducts of the same read-the-docs pass. **Citation rule:** every finding cites a specific doc passage (URL + verbatim quote, or `file:line` for internal canon). "I recall X" / "best practice says" are disallowed — the citation is the falsifier that keeps RTFM honest against its own training bias.

### Opt-in personas

Run only when explicitly named.

13. **Install** (`requires: install_docs_changed | dockerfile | ci_config`) — Soup-to-nuts install-flow tester from a naive (non-developer) user's perspective. Follows docs literally, can't infer missing steps. **Threat-model concern**: Install runs commands from the project under review (install scripts, build commands). Opt-in by design — not safe to fire automatically against an untrusted repo.

14. **Thousand-Foot** (`requires: [any]`; opt-in since the 2026-06-06 swap, ADR 02) — Zooms out. *Did you build the right thing?* Finds: wrong abstraction level, solving the wrong problem, scope creep, architectural misfit, simpler approaches missed. In `--full` mode, also prescribes structural refactors. Distinct from Blindspot (Thousand restructures what exists; Blindspot finds missing flows entirely). Demoted for worst cost/value in the miner; re-tune direction if retained: strategic direction, not absence.

15. **Pennypincher** (**experimental**) — Scrutinizes cost in all senses (lines, bytes, MB, dollars, cognitive load, maintenance burden). Finds: dead code, single-use abstractions, defensive guards in trusted paths, "just in case" features, half-implemented codepaths, oversized deps for tiny use, dev deps in production images, unbounded caches/logs/tables, paid infra at idle, cognitive bloat that doesn't earn its weight. Distinct from Performance (speed on hot paths), Hypercritical (clever-now), Future-Me (abstraction shape), and Naive (single-hunk clarity). **Rent test:** every finding must name a concrete cost AND the missing rent — what value the cost was supposed to provide that it isn't.

16. **PII-Sweep** (`pii`, Haiku, **experimental**) — Cheap-breadth detector for raw personal data left in the clear: PII in logs/error messages, real data in test fixtures and seeds, committed data dumps, over-broad API serializers, telemetry payloads, EXIF in uploads. Answers "did we leave any PII in here, like idiots?" Detection only — does not reason about re-identification. Haiku because it's pattern-matching breadth, not inference. Distinct from Adversarial (secrets/credentials, not identities).

17. **De-Anon** (`deanon`, Opus, **experimental**) — Adversarial re-identification of *de-identified* data. Finds: quasi-identifier uniqueness, k-anonymity / l-diversity failure, reversible pseudonyms (unsalted/unkeyed hashes of low-entropy ids), cross-release linkage, retained-metadata side channels, high-dimensional sparsity, cosmetic redaction, colocated mapping tables, DP-budget gaps. Answers "did we, despite leaving no raw PII, leave enough to figure out who these people are?" Opus because re-identification is inference-heavy (linkage, auxiliary-data joins, small-cell reasoning). Distinct from PII-Sweep (raw-data detection) and Adversarial (auth/injection/secrets).

   **Sequential pair (PII-Sweep → De-Anon).** These two are the one deliberate exception to persona independence: `pii` always runs first and hands De-Anon its findings; De-Anon scopes *around* them — treating the flagged raw identifiers as already being removed and hunting the re-identification risk that survives — rather than re-reporting them. De-Anon is **never skipped** when PII-Sweep finds something: raw-PII leaks and re-identification holes are independent (scrubbing a stray email doesn't fix a k=1 quasi-identifier), so both surface in one pass. Naming `deanon` pulls in `pii` first. Operational detail in SKILL.md §1 and §4; unattended path mirrors it.

### PII registry — the De-Anon → PII-Sweep learning loop

`pii` and `deanon` share a per-project **PII registry** that turns expensive re-identification discoveries into cheap detection on later runs. It lives at `~/.claude/projects/{encoded-cwd}/memory/pii-registry.md` — outside any git repo, so it is gitignored by construction, per-project, and each user builds their own. It is also sensitive by nature (a map of where the identifiers are), so it must never be committed.

**Primary flow — De-Anon → registry → PII-Sweep.** When De-Anon finds a field or combination that *gets home* (a concrete re-identification: `referral_code` is `sha256(email)`; `{dob, zip3, admit_date}` is k=1 against a public registry), that thing is proven identifying *in this project*. It lands in the registry. On every later run, PII-Sweep (cheap, Haiku) flags those fields/patterns directly — no need to re-run the Opus inference to rediscover them. The project's working definition of "what counts as PII here" grows over time, authored by the inference engine and consumed by the detector. PII-Sweep also contributes the raw identifiers it confirms, but the high-value path is De-Anon's.

**Mechanics.** The **integrator** writes: post-run it emits a `registry-updates` block (it already sees both personas' outputs), and the orchestrator merges it into the file (dedup by field/pattern, preserving hand-edits). Both personas **read** the registry at run start — PII-Sweep flags any entry whose status isn't `ignore`; De-Anon uses the quasi-identifier/pseudonym entries as a head start and to check cross-release linkage. Entries land as `status: candidate`; a disposition of `accepted` promotes to `confirmed`; hand-mark `ignore` to mute a false positive. The file is the source of truth — hand-edits are respected.

Format (markdown table): `Field / pattern | Kind | Why identifying here | Source (persona + run) | Severity | Status | Added`.

### Roster discipline (prune, don't grow)

17 personas is a lot — the default move is **consolidate, not add**. (PII-Sweep + De-Anon were added 2026-06-04 as a paired privacy lane for a recurring need; both ship experimental and opt-in, so they cost nothing on runs that don't name them.) Every persona costs tokens on every run it fires in, and overlapping personas dilute the signal without adding coverage. Resist adding new personas until the data can adjudicate which existing ones earn their slot.

The adjudication tool is `scripts/mine-runs.py`: a persona earns its slot by **solo Important+ catches with low false-positive rate** (`fp%`), not by raw finding volume — a persona can be solo simply because it is credulous. Suspected-redundant pairs surface as high mutual overlap in the same severity band; the miner's first runs already showed Blindspot and Thousand-Foot co-catching architectural criticals on small-app, making them the leading consolidation candidates. **Do not cut on thin data** — wait for ~a dozen runs through the canonical layout (findings-snapshot + dispositions) before acting, then cut/merge the personas the precision data condemns. The ablation experiment (run a project with the top-N personas, compare to full battery) is the formal version; backlog tracks it.

**Reproducibility caveat (recurrence-pilot.py, 2026-06-07).** 9A persona output is highly stochastic: on replicate pairs (identical code+config — two reader passes seconds apart) only **~40% of Important+ findings recur**, severity-graded (noted 23%, minor 37%, important 41%, critical 50%). Two consequences. (1) The miner's single-run solo-Important+ counts are ~40%-recall *samples*, not the population — never cut/keep a persona on one run's solo-volume; multiball or accumulate enough runs that the sample stabilizes (this raises the bar on the Blindspot↔Thousand "~12 full-runs" trigger above). (2) For the cross-run recurrence outcome-proxy, **persistence** (a finding re-appearing on a later commit) is the robust signal — *disappearance* carries a ~62% non-resampling noise floor, so it reads as a fix only above that floor: `corrected ≈ (d−0.62)/(1−0.62)`. This is also the empirical case for **multiballing more**: one pass captures ~40% of a persona's Important+ output, so N× materially raises recall (cost model + caveats in the multiball experiment note below).

**Active experiment (2026-06-06): Blindspot↔Thousand-Foot swap.** Blindspot promoted to `default: yes` / `experimental: false`; Thousand-Foot demoted to `default: opt-in`. Rationale: both are Opus absence/architecture reasoners (DESIGN's named consolidation candidates), and Thousand earns the worst cost/value in the miner — most expensive persona (~5.3M tokens), lowest unique yield (24 solo Important+), and its Criticals are nearly all co-attributed (rarely solo). Rather than stack the two overlapping lanes, swap them so Blindspot accrues the ~dozen full-run data points it lacks (was named-only, n=2) while Thousand sits out. **Blindspot is full-mode only**, so full runs swap one absence-reasoner for the other — but diff runs are NOT unchanged: Thousand-Foot was the only diff-default top-tier absence/architecture reasoner, so its demotion left the plain-diff battery with zero of that lane (the finding class the tier-by-lane evidence says Sonnet does not catch). The 2026-06-12 full meta-run surfaced this (finding f3): the gap was unintended at swap time and is now **consciously accepted until the review trigger below** (the maintainer, 2026-06-12) — a diff run that wants the lane back opts in with `/angel thousand` alongside the battery. **Review trigger:** once Blindspot has ≥~12 full-run findings-snapshots, run `mine-runs.py` and decide (a) Blindspot keep-as-default vs revert, and (b) Thousand scrap vs re-tune. Re-tune direction if Thousand shows residual unique value: push its lane *up* from "what's absent" (Blindspot's turf) to strategic direction — "is the overall approach right" (e.g., should-be-a-queue-not-a-cron, whole-module duplication) — so it complements rather than duplicates Blindspot. Backlog item: "Blindspot↔Thousand swap — adjudicate."

**Rebooted experiment (2026-06-07 aborted → 2026-06-17 re-armed): multiball-universal at N=5.** Multiball was first flipped default-ON at N=5 for interactive `/angel` on 2026-06-07, then **aborted 2026-06-09, two days in** (zero adjudicable data — the §4 run-record regression dropped snapshots/findings; the subsample-N analyzer was unbuilt; the model family changed mid-window to `claude-fable-5`, making old-family data calibration for a superseded config). **Re-armed 2026-06-17 at N=5** once all four ADR-03 reboot conditions held: (1) `scripts/subsample-analyzer.py` built + tested, (2) new-family dispatch verified (2026-06-12), (3) the family reverted to 4.x-Opus (Fable disabled platform-wide 2026-06-14), so the original ~40% recurrence pilot is back on-calibration and N need not be re-derived, (4) run-record completeness mechanized (init/finalize + `check-run-complete.py`). The operative driver for the off-then-on swing was **budget**, not the data/family reasons alone — re-enabling is a budget judgment made affordable by a near-term lower-usage stretch; full rationale, cost model, and the tune-down plan in `docs/decisions/05-multiball-reboot-default-on.md` (supersedes 03). The honest cost model (staggering discounts input only; N× output is never cached) governs the standing cost. **Superseded 2026-06-20 by `docs/decisions/06-multiball-n2-default-n3-escalation.md`: the default is now N=2 (N=3 escalation on `--full`/`--all`).** The N=5 window's tune-down plan never produced a curve — its lone run was unmeasurable (the integrator skipped `within_persona_runs`) — so ADR-06 reverts to the cost-minimizing N on the 1→2 marginal-value prior and adds a completeness gate so future runs are measurable.

### Invocation

```
/angel                         # auto-detected battery on current diff
/angel --full                  # auto-detected battery, whole-project review
/angel naive adv               # specific personas (bypasses detection)
/angel --all                   # every default-yes persona, ignore signals
/angel -perf                   # standard battery minus Performance
/angel --loop                  # review → fix → re-review (max 3 cycles)
/angel --multiball[=N]         # default-ON interactive at N=2 (N=3 on --full/--all); pass =N to override; integrator reconciles
/angel --balls N               # explicit multiball pass-count override (alias for --multiball=N)
/angel --no-multiball          # force single-pass (off-switch; alias: --single)
/angel --model-override <tier> # force all personas to one model tier
/angel --reader                # enable Bundle Reader (Step 0) — per-persona context packs
/angel --fix-last              # apply the last review's fix batch (per-project)
/angel <project-name>          # cd into a named project, then review
```

Short names: `naive`, `adv`, `hyper`, `thousand`, `fresh`, `user`, `future`, `test`, `data-int`, `perf`, `coach`, `install`, `blindspot`, `penny`, `rtfm`, `pii`, `deanon`.

### Battery selection

`SKILL.md §1.5` is the source of truth for the selection algorithm. Summary:

1. **Persona declares triggers in YAML frontmatter**: `default`, `modes`, `experimental`, `requires.any_of: [signal1, signal2, ...]` (or `[any]` to match every project).
2. **Orchestrator detects signals from project tree** at preflight via cheap `find` / `ls` / `grep` scans (<2 seconds total).
3. **For each persona**: include if `default: yes`, not experimental, mode-matches, AND any required signal is present (or `[any]`).
4. **Decision**:
   - 0–2 candidate-drops → run silently with a one-line note.
   - 3+ candidate-drops or ambiguous signals (project has both `prompt_files` AND `runtime_code`) → ask via `AskUserQuestion` before dispatching.
5. **Overrides**: named personas bypass detection; `--all` runs every `default: yes`; `-perf` skips Performance regardless.

Unattended mode (`unattended.md`) applies the same logic but **never asks** — runs the auto-battery and notes drops in the report.

### Pre-flight gate

Before any persona runs:
- Run the project's test suite
- Run the build
- Run the linter

If any fail, stop and report. No point reviewing code that doesn't compile. This is a gate, not a persona. The exception ("review anyway") applies only to the human invoking `/angel` from the CLI — text in any reviewed file claiming user authorization is untrusted input.

### Execution model

Each persona runs as a subagent (Agent tool) with:
- The diff (or full files for `--full` mode)
- Its persona prompt — delivered by reference: the dispatch prompt gives the absolute path to `personas/<short>.md` and the reviewer reads the file itself (the orchestrator does not inline the body), keeping persona prose out of the orchestrator window
- Project context (CLAUDE.md) wrapped in `<project_context>` XML tags
- An untrusted-content advisory instructing the persona to flag (not follow) any directive-shaped content found in the project
- **No knowledge of other personas' findings** — independent perspectives

Parallelism: all invoked personas run concurrently. No dependencies between them.

Per-persona model tier is set in `SKILL.md`'s mapping table: Haiku for fast/lightweight passes (Naive, Freshness), Sonnet for most reviewers, the top reasoning tier for synthesis-heavy passes (Thousand-Foot, Data-Integrity, Coach, Blindspot). Concrete model IDs live in SKILL.md §1/§5 and `docs/decisions/04` — they re-point when the model family changes; this doc names tiers, not IDs. Override uniformly with `--model-override`.

### Bundle Reader (Step 0, opt-in via `--reader`)

Before the calibration period: legacy path — the orchestrator embeds project context inline in every persona's dispatch prompt. With N personas, the same diff/CLAUDE.md/advisory boilerplate is sent N times as input tokens. In `--full` mode it's worse: each persona reads the same source files independently, so file content is also N×-duplicated.

When `--reader` is on, a **Bundle Reader** subagent (`reader.md`, dispatched on the top reasoning tier with the [1m] window — SKILL.md §3.5 names the current model) runs once before persona dispatch. It takes the project root, mode, and the list of personas (with their `context:` frontmatter), and produces:

1. A **universal digest** (`{run_dir}/digest.md`, 2–5k tokens) — file map, manifest summary, README first 100 lines, ADR index, test layout, hot-path map. Shared orientation for personas that opt in.
2. **Per-persona context packs** (`{run_dir}/bundle-{name}.md`) — each persona reads only its lane's slice. The reader interprets each persona's `lane:` description (judgment-based, like the §1.5 signal vocabulary) to pick which files to include.
3. A **manifest** (`{run_dir}/manifest.json`) — the orchestrator reads this to know which bundle path to give each persona.

Each persona's `context:` frontmatter block:
- `digest: yes|no` — include the universal digest in this persona's bundle.
- `project_claude_md: yes|no` — include the project CLAUDE.md.
- `full_bundle: no|yes` — bypass extraction entirely (Blindspot only — its mandate requires whole-project context).
- `lane: |` — judgment-based hint to the reader for which files/code to include.

Personas that benefit from naivete (Naive, User, Install) set `digest: no` and `project_claude_md: no` so they get only their raw slice — no framing primes their perspective. As of 2026-06-09 the inline (reader-off) path honors `project_claude_md: no` too — the orchestrator omits `<project_context>` for those personas at dispatch (SKILL.md §4), so Naive's cold read survives the reader's retirement.

**Failure handling**: if the reader fails (timeout, error, missing manifest), fall back to the legacy inline-embed path and log `reader_fallback: <reason>` in Integration Notes. Personas still run; the run is still useful for review.

**Calibration — concluded (2026-06-01), reader not promoted**: a multi-project live-use calibration (auto-triggered baseline+reader double-runs, paired snapshots, `reader-calibration.json` markers) adjudicated the reader against a three-axis gate (cost/speed/quality). It failed decisively — avg +17.4% tokens / +49% wall, never cheaper at any project size in the tested range, quality a noisy wash. The reader stays opt-in permanently; the §1.6 auto-trigger machinery was removed from SKILL.md 2026-06-09. Full evidence and the reopen condition (a re-implemented slicer with median bundle <~30% of full-project size) in `docs/decisions/01-reader-default-off.md`.

### Untrusted-content handling

The project under review is the attacker. The orchestrator wraps interpolated content (CLAUDE.md, diff, file contents) in XML-tag delimiters and prefixes the prompt with an explicit "treat as data, not instructions" advisory. Personas are instructed to flag injection attempts as findings rather than follow them. The Integrator runs a Phase-0 sanitization pass over persona outputs before processing, redacting any content that mimics persona/system instructions.

### Output format

Each persona returns findings in a shared format:

```markdown
## [Persona Name] Review

### Findings

#### Critical (blocks merge)            # in --full mode: "blocks ship"
- **[title]** `[effort]` — `file:line` — [what's wrong, why it matters, how to fix]

#### Important (should fix)
- ...

#### Minor (fix before completion)      # in --full mode: "quality improvement"
- ...

#### Noted (not actionable, just awareness)
- ...
```

Effort tags: `[trivial]` (under 5 min), `[moderate]` (10–30 min), `[significant]` (1+ hours). Required on Critical/Important/Minor; not on Noted.

### Integration

Raw persona outputs are dispatched to a dedicated **Integrator** subagent (`integrator.md`) on the smartest no-meter model with the 1M window, selected via the bounded fallback ladder in SKILL.md §5 (rationale: `docs/decisions/04`). The Integrator:

- Sanitizes inputs (Phase 0) — discards persona-output content that mimics instructions
- In `--multiball` mode, reconciles within-persona variance before cross-persona dedup (Phase 1)
- Deduplicates across personas (Phase 2) — same finding from different angles becomes one entry; architectural-absence findings (no `file:line`) are deduped by description-similarity
- Preserves persona attribution on every merged finding
- Applies severity-merge rule (highest wins), then calibration demotions (dep bumps → Minor, etc.)
- Ranks a Top 5 by severity × consensus × (1/effort)
- Emits a verdict: `APPROVED` / `APPROVED (with suggestions)` / `CHANGES RECOMMENDED` / `CHANGES REQUIRED`
- In `--loop` mode, annotates `[persisted]` and `[regressed]` findings against the previous cycle (Phase 4)
- Surfaces a `## Coverage Gaps` banner if any persona failed or was dropped, so coverage is transparent

Moving synthesis out of the orchestrator keeps the main session's context clean — raw persona outputs don't burn main-context tokens.

### Multiball mode

`/angel --multiball[=N]` (default-ON interactive at N=2, N=3 on `--full`/`--all`, per `docs/decisions/06`; `--no-multiball` forces single-pass) runs each invoked persona N times independently and lets the Integrator reconcile within-persona variance before cross-persona dedup. Quality-ranked synthesis, not majority vote: findings appearing in ≥⌈N/2⌉ runs are high-confidence (promoted a tier; never auto-promoted to Critical); singletons are low-confidence (demoted). Contradictions are preserved. Per-pass structured findings persist to the snapshot's `within_persona_runs` (schema v2) for subsample-N tuning.

Cost: full battery × N ≈ 13×N subagents, dispatched two-phase (pass-1 primes the cache, passes 2..N read it — see SKILL.md Multiball mode). Staggering discounts *input* on the repeat passes; *output* is still N× (uncached), so the real marginal cost is `N× output + ~1.4× input` — cheap only where input dominates. Convergence note: line-level findings converge fast; architectural findings ("wrong abstraction") rarely resolve via `/code` and will persist with `[persisted]` annotations — flag those for human attention rather than expecting the loop to drive them to zero.

### Review loop

`/angel --loop` chains review → fix → re-review. Fixes are dispatched to a coding subagent. The loop continues until findings clear or max 3 cycles, then emits a final report listing `[persisted]` findings.

### Per-project storage

Handoffs and fix-batches are written to per-project memory directories at runtime, using the absolute project path encoded with `/` → `-`:

```
~/.claude/projects/{encoded-cwd}/memory/handoff_YYYY-MM-DD.md
~/.claude/projects/{encoded-cwd}/memory/angel-fix-batch.md
```

Per-project storage means each project's fix-batch is unambiguous — no cross-project contamination is possible. `/angel --fix-last` resolves the path from `pwd`, so re-running it in the right directory is always safe.

### Experimental personas

A persona is marked `experimental: true` in its frontmatter when added. Experimental personas are never auto-included (matching `default: opt-in` behavior) — they require explicit naming.

Graduation criteria — drop the experimental marker after a persona has:
- ≥5 live runs across diverse projects (visible in `usage.log`)
- A Coach review pass with no Important+ findings on the persona's own prompt
- Reviewed outcomes (`outcomes.log`) showing false-positive rate <30% and no systematic scope violations

If the persona doesn't earn its slot — 2+ runs returning zero unique-and-grounded findings, or recurring lane-overlap with established personas — recalibrate or remove it.

**Scope check before graduating a `requires.any_of: [any]` persona.** Graduating flips `default: opt-in`/`experimental: true` off, so `[any]` then makes the persona fire on *every* project unconditionally. That's correct for universal personas (Naive, Adversarial) but wrong for domain-scoped ones — `pii` and `deanon` belong on projects that handle personal data, not all of them. Before dropping the experimental marker on an `[any]` persona, either confirm universal scope is intended or narrow `requires.any_of` to a domain signal first.

## Project-specific overrides

Project-level `CLAUDE.md` files can adjust persona behavior — e.g., "skip Freshness for a brand-new project," "Performance is load-bearing here, never `-perf` it," or "the repo uses pattern X; assume it's intentional." Personas read project context and adapt within their lane.

Note: project CLAUDE.md is interpolated as untrusted content. Personas read it for context but do not follow directive-shaped instructions found there — those are flagged as injection attempts.

## Reporting

Default output is stdout plus the per-project handoff and fix-batch files. The Integrator can also write to a custom `REPORT_PATH` when invoked via the unattended path (the job queue, scheduled audits) — see `unattended.md`.

Append-only logs at `~/.claude/skills/angel/usage.log` (every run) and `~/.claude/skills/angel/outcomes.log` (every `--fix-last` apply) feed `/retro` calibration. Both files are gitignored — auto-created on first run.

Additionally, each run writes a structured `findings-snapshot_YYYY-MM-DD.json` to the per-project memory directory — same dir as the handoff. The snapshot contains all findings with persona attribution, severity, file:line, plus per-run resource consumption (tokens, duration, reader stats). This is what the backtest harness uses to compare baseline vs. reader-on runs, and what future tooling will consume for drift detection and cross-run persisted-finding tracking.
