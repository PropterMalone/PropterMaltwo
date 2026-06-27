---
id: 05-multiball-reboot-default-on
name: Re-arm multiball default-ON at N=5 for interactive runs
date: 2026-06-17
status: superseded-by-06
supersedes: 03-multiball-abort-family-reboot
superseded-by: 06-multiball-n2-default-n3-escalation
commits: [39280e3]
---

# Re-arm multiball default-ON at N=5 for interactive runs

**Decision**: Multiball is **default-ON at N=5 for interactive `/angel`**, effective 2026-06-17. `--multiball=N` overrides N per run; `--no-multiball`/`--single` forces single-pass. Unattended (`claude -p`) stays single-pass. N=5 is provisional — the target is to tune it down to the cheapest sufficient value once `scripts/subsample-analyzer.py` has a recall-vs-N curve from real runs. This supersedes ADR-03, which aborted the first (2026-06-07) default-ON N=5 attempt.

**Why now — the operative driver is budget, not the data/family reasons.** ADR-03's stated abort reasons were "zero adjudicable data" and "model family changed mid-window." Both are now resolved (see reboot conditions). But the binding constraint that kept multiball *off* through the intervening Fable-dead period was **cost**: multiball multiplies the uncacheable output of every interactive full run, and on Opus 4.8 (pricier per token than Fable was) that is a standing ~2.7× spend warm-cache, up to 5× cold (see the cost model below — the earlier "~2×" shorthand understated it). Re-enabling is therefore a **budget judgment**, made by the maintainer, and made affordable by a specific near-term condition: a temporary lower-usage stretch during which interactive `/angel` volume drops. The reboot conditions below make it *safe* to re-arm; the budget call is what makes it *happen now*. [recalled: maintainer directive — run N=5 and tune down from there; a near-term lower-usage stretch makes the premium affordable]

**Why N=5 and not N=3** (the cheaper option, recommended on cost grounds): two reasons favor 5 during this window. (1) Recall — one pass captures only ~40% of a persona's Important+ findings (recurrence-pilot.py), so more passes is strictly higher recall; the reduced-usage headroom removes the cost objection that argued for 3. (2) Data — N=5 gives the subsample analyzer a full k=1..5 recall curve per run, so the tune-down decision is made on the widest possible evidence rather than capped at k=3. The marginal recall of pass 4→5 over N=3 is **unmeasured** (no real multiball data exists yet) — N=5 is bought primarily to *measure* that curve during the affordable window, not on a claim that 5 is a known recall optimum. N=5 is explicitly **provisional**.

**Reboot conditions (all four resolved as of 2026-06-17 — condition 3 by family reversion rather than a fresh pilot run, see its entry):**

1. **Subsample-N analyzer built + tested.** `scripts/subsample-analyzer.py` ships with 24 hand-verified tests wired into `test_scripts.sh` (72 total). The shared matcher was extracted to `finding_match.py` and recurrence-pilot.py refactored to import it, verified byte-identical. [ran: `scripts/test_scripts.sh` → 72 passed, 0 failed]
2. **New-family dispatch verified.** MET 2026-06-12 (tier self-report probes; annotated in ADR-03/04).
3. **N re-derived for the current family — satisfied by reversion.** ADR-03 cond 3 required re-running the recurrence pilot on the *new* family (then Fable) to set N. Fable was disabled platform-wide 2026-06-14, reverting the session/dispatch family to 4.x-Opus — the exact family the original ~40% recurrence number was measured on. The N basis (N=3 as the data-justified floor; N=5 as the recall-maximizing ceiling we're starting at) is therefore back on-calibration without a fresh pilot. [recalled: CLAUDE.md 2026-06-14 — "Fable 5 is disabled platform-wide for everyone"]
4. **Run-record completeness mechanized.** MET 2026-06-12 — `init-run.sh` / `finalize-run.sh` gate on `check-run-complete.py`, so the snapshot/findings regression that produced ADR-03's "zero adjudicable data" cannot silently recur.

**Cost model (standing cost of this decision).** Multiball N=5 ≈ `5× output + ~1.4× input` warm-cache (≈2.7× total on a ~90/10 input/output split), up to `5×` cold, because output is never cacheable and the staggered Phase-A→B priming only discounts repeat-pass input. So a full review's cost scales by roughly that multiplier at N=5 — a material standing premium concentrated in the largest cold-cache runs, not the median. Diff-mode multiball is cheap (small input). The input/output split is inferred (~90/10), so treat the multipliers as order-of-magnitude, not precise.

**Could-be-wrong-if** (falsifiers — any one flips the decision):
- The analyzer's recall-vs-N curve, once ≥10 full N=5 runs accrue, shows `recall(3) ≥ recall(5) − 5 points` (a plateau) → drop default to N=3 (or lower to the smallest N within 5 points of recall(5)). This is the expected tune-down, not a failure.
- Session-level spend during the lower-usage stretch materially exceeds expectation (concrete: weekly spend > 1.5× the pre-flip interactive-`/angel` baseline attributable to multiball) → drop N or revert to opt-in before the window ends.
- The lower-usage stretch does **not** lower usage as assumed (interactive `/angel` volume stays at or above baseline) → the budget premise is void; reassess N immediately rather than waiting for the curve.

**Window-end backstop (calendar-bound — the premium is opt-out-by-time, not opt-out-by-vigilance).** N=5 over N=3 is justified *only* by the lower-usage stretch, but it is installed as a standing default; in the expected good case (usage drops, spend stays under the tripwire) none of the falsifiers above fire, so the premium would silently ride into normal-usage weeks — and the low volume that makes it "safe" is the same low volume that starves the analyzer of the ≥10 runs needed to tune down. Backstop: **at the end of the lower-usage stretch, if `subsample-analyzer.py` does not yet have ≥10 full N=5 runs to tune from, drop the interactive default to N=3** pending the curve (mirrors ADR-03's expiry discipline; the first 2026-06-07 window had an explicit expiry and this reboot must not regress that). Tracked in `backlog.md` (the REBOOTED item carries the trigger).

**Rejected alternative — N=3 (the cost-minimizing recommendation).** Lower standing cost and already data-justified as the recall floor. Rejected for *this window* because the reduced-usage headroom makes the higher spend affordable and the per-run data value (full k=1..5 curve) is maximized at 5 — i.e. paying more now buys a faster, better-grounded tune-down. The decision is reversible the moment the curve or the spend says otherwise (see falsifiers).

**How to apply**: SKILL.md §1 flag lines + §4 Multiball section flipped to default-ON N=5 interactive; DESIGN.md "Rebooted experiment" note + usage examples + integrator description updated; backlog.md multiball item marked REBOOTED and analyzer item marked SHIPPED; ADR-03 marked `superseded-by-05`. Unattended path unchanged (single-pass). Implementing commit: `39280e3`.
