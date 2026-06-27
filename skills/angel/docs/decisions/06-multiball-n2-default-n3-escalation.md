---
id: 06-multiball-n2-default-n3-escalation
name: Multiball default N=2 interactive, N=3 escalation on --full/--all
date: 2026-06-20
status: active
supersedes: 05-multiball-reboot-default-on
commits: [7062965]
---

# Multiball default N=2 interactive, with N=3 escalation

**Decision**: Multiball is **default-ON at N=2 for interactive `/angel`**, effective 2026-06-20. It **escalates to N=3** automatically when `--full` or `--all` is passed, and on demand via `--balls N` (or `--multiball=N`); an explicit override always wins over the auto-escalation. `--no-multiball`/`--single` forces single-pass. Unattended (`claude -p`) stays single-pass. This supersedes ADR-05 (N=5 starting point).

**Why now.** ADR-05 set N=5 as a *provisional* starting point, justified **only** by a temporary lower-usage window during which the N=5 output premium was affordable, with the explicit plan to "tune down from the recall-vs-N curve once ≥10 runs accrue." That window is ending and two things are now clear:

1. **The curve never materialized.** Exactly one N=5 run landed (2026-06-19, `<run-id>`). It is **unmeasurable**: its 5 passes per persona used ≥3 different free-form output formats, and the integrator never emitted the `within_persona_runs` per-pass record (it improvised prose `consensus` strings instead). `subsample-analyzer.py` reads **zero** multiball snapshots. So ADR-05's core mechanism — buy N=5 to *measure* the curve — did not execute. [ran: `subsample-analyzer.py --runs-dir ~/.angel/runs` → "0 multiball snapshots"; ran: inspected `<run-id>/findings-snapshot.json` — no `within_persona_runs` key, no `version:2`]
2. **The premium loses its justification as usage normalizes.** ADR-05's N=5 cost (≈2.7× output warm-cache, up to 5× cold) was explicitly contingent on the low-usage window. Past it, the standing premium is not justified by any measured recall gain (there is none) — so the default reverts toward the cost-minimizing N.

**Why N=2 (not N=1, not N=5).** This is decided on **cost + the marginal-value prior**, NOT on a measured saturation curve — be explicit, because ADR-05's lesson (a ~2× cost overclaim caught at the gate) was precisely about not dressing a prior as data:
- The prior: a single pass captures only ~40% of a persona's Important+ findings (recurrence-pilot.py, *cross-run* number — itself only a proxy), so the **1→2 pass jump is where multiball's recall recovery concentrates**; returns diminish after. N=2 keeps that high-value second pass.
- Cost: N=2 ≈ `2× output + ~1.2× input` (≈1.3× total on a 90/10 split) vs N=5's ≈2.7× total — roughly **50% cheaper per multiball run** on the total-cost basis (1.3/2.7); equivalently, N=2 runs 60% fewer output passes (2 vs 5, and output is the uncacheable cost). One basis, stated once: ~50% total. It keeps the largest runs' cost in check without escalation.
- N=3 is reserved for runs whose blast radius or input size justifies the third pass (`--full`/`--all`, or explicit `--balls 3`).

**The saturation hypothesis is a hypothesis, not a result.** The framing that motivated this change — *"recall saturates by N=2, is ~always complete by N=3"* — is a **maintainer intuition** [recalled: maintainer directive 2026-06-20], not a measured finding. The one run that exists cannot confirm or refute it (see #1 above). It is recorded here as this ADR's **open falsifier**, now testable because of the recording fix shipped alongside this decision.

**Recording fix shipped with this ADR (so the next decision has data).** The root cause of #1 — the integrator silently skipping `within_persona_runs` while `check-run-complete.py` only checked the *whole snapshot block* — is closed: `check-run-complete.py` now fails a multiball run (N≥2, detected from the snapshot's `multiball` field or `*_ball*.md` passes on disk) whose snapshot lacks a well-formed `within_persona_runs`. Because that script is the final stage of `finalize-run.sh` (the mandatory end-of-run gate, §8b/§8c), every future N=2/N=3 run either records its per-pass data or fails loudly. [ran: `test_scripts.sh` → 76 passed, 0 failed]

**Cost model.** Per full run, at the N=3 escalation: ≈`3× output + ~1.3× input` (≈1.8× total warm-cache); at the N=2 default: ≈1.3× total warm-cache. Diff-mode multiball stays cheap (small input). Figures inherit ADR-05's ~90/10 input/output split caveat — order-of-magnitude, not precise.

**Could-be-wrong-if** (falsifiers — any one flips the decision):
- Once ≥8 measurable multiball runs accrue, the analyzer shows `recall(2) ≤ recall(3) − 8 points` materially and repeatably → bump the interactive default to N=3 (the second pass is leaving real recall on the table). This is the saturation hypothesis's failure mode.
- The analyzer shows `recall(2) ≤ recall(1) + 3 points` (the second pass adds almost nothing) → the multiball premise itself weakens for that lane; consider dropping multiball to opt-in rather than paying 2× for a no-op.
- Session-level spend on N=2 still trips the cost tripwire (weekly spend multiball attribution > 1.3× the single-pass interactive baseline) → drop to opt-in.

**Backstop re-aim.** ADR-05's window-end backstop cron applied "<10 multiball runs → DROP default to N=3" — now wrong-footed: N=2 is already the default, and the analyzer reads zero regardless of run count until records accrue. Re-aim (or retire) it to test the *first* falsifier above — "is N=2 leaving recall on the table" — and only once `subsample-analyzer.py` reports a non-zero measurable-run count (which the recording fix now makes possible). See `backlog.md`.

**Rejected alternatives.**
- **Keep N=5.** Rejected: its sole justification (the reduced-usage window + measuring the curve) is spent — the window is closing and the measurement failed. Paying ~2.7× for unmeasured recall is the exact overclaim posture ADR-05's gate was meant to prevent.
- **Drop to N=1 (no multiball).** Rejected: the 1→2 recall jump is the best-supported part of the whole multiball case; abandoning it discards multiball's main value to save the cheaper of the two passes.
- **Fixed N=3 always.** Rejected on cost for the common (diff, targeted) case; N=3 is better spent as an escalation tied to leverage/size than as a flat default.

**How to apply**: SKILL.md §1 flag lines (`--multiball`, new `--balls N`) + §4 Multiball section (header, N-resolution order, honest-justification paragraph, cost model, batching math) flipped to N=2 default / N=3 escalation; README + DESIGN.md usage lines and N=5 references updated; `check-run-complete.py` (multiball `within_persona_runs` gate, structured-shape validation) + `test_scripts.sh` extended; SKILL.md §8c note added; `integrator.md` Phase 1 made mandatory-emission when multiball input is present; ADR-05 + DESIGN.md marked superseded; `multiball-backstop.sh` tombstoned + crontab line removed, replaced by the silent-until-data re-tune watch (`multiball-retune-watch.sh`). Unattended path unchanged (single-pass).
