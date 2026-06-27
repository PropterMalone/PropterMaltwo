---
id: 01-reader-default-off
name: Keep the Bundle Reader default-off (do not promote)
date: 2026-06-01
status: active
supersedes: null
commits: [261b1c8]
---

# Keep the Bundle Reader default-off

**Decision**: Do not promote the `/angel` Bundle Reader (`--reader`) to default-on. It stays opt-in; the §1.6 calibration default-flip does not happen.

**Why**: A multi-project calibration (a mix of small/medium and larger codebases) shows the reader **failing its sole purpose**. Its entire reason to exist is cutting per-persona cost via context slicing. Instead it is **more expensive on every project** — avg **+17.4% tokens, +49% wall**, never cheaper anywhere in the range. The steelman (it pays off on large codebases where inline context is huge) was **disconfirmed**: the larger projects were still +14% and +30%. Root cause is observable: the bundles came out 54–83KB — near-zero slicing — so personas get ~full context anyway and the reader subagent (60–240K tokens/run) is pure overhead. Findings quality is a **noisy wash, not an offsetting win**: on one larger project the reader missed 2 real Criticals (a dependency CVE + a data-loss bug) because sliced bundles starved the `fresh`/audit persona; on the other it *correctly* escalated a bug the baseline under-rated (Important→Critical). Both directions occur → no net quality gain to justify the cost. A cost-cutter that raises cost ~17% with no quality upside has no case. [ran: `finalize-calibration.py`, per-Agent meter; read: per-project findings-snapshots]

**Rejected alternative**: Run additional larger projects before deciding. Dropped because the token-cost result is **consistent and monotonic across the entire size range** — there is no size at which the sign flips, and the slicing mechanism (bundle ≈ inline) explains why. More same-implementation data cannot rescue it; they would move the average, not the verdict.

**Could-be-wrong-if**: a **re-implemented** reader with genuinely aggressive slicing (median bundle < ~30% of full-project token size) is re-calibrated and shows **negative average token delta on ≥3 projects with 0 lost Criticals** (matched, not text-heuristic). Check: re-run `finalize-calibration.py` after the slicer rewrite; if avg `total_tokens_pct` goes negative and `critical_lost` is 0 across the set, reopen this decision. The current verdict indicts *this build* (near-zero slicing), not the reader concept.

**How to apply**: Keep `--reader` opt-in and the default `off` in `SKILL.md` (§1, §3.5) and `unattended.md`. Do **not** flip the §1.6 calibration default. Revisit only after a slicer re-implementation — not after accumulating more data on the current build. The `reader-calibration.json` markers (one per project) and the finalizer are the evidence of record.

---

## Evidence (summary)

| Set | Projects | avg token Δ (reader vs baseline) | avg wall Δ | cheaper anywhere? |
|-----|----------|----------------------------------|------------|-------------------|
| small/medium | most of the set | +16.5% | +40% | only one project, −2.2% (marginal) |
| larger | the rest | +30% / +14% | +86% / +112% | no |

- Metered cost/wall are trustworthy (per-Agent meter). Finding lost/gained counts are a **text-match upper bound** — they over-count reworded/cross-file severity reclassifications; do not treat raw `critical_lost` as ground truth.
- Qualitative anchors: one larger project's reader **missed** a dependency CVE + a data-loss bug; the other's reader **caught** an under-rated authorization gap. Mechanism for misses: per-lane bundle slicing starves dependency/audit context.
- Markers: `~/.claude/projects/*/memory/reader-calibration.json` (13). Finalizer: `~/.claude/skills/angel/scripts/finalize-calibration.py`.
