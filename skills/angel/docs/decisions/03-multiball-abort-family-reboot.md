---
id: 03-multiball-abort-family-reboot
name: Abort the multiball default-ON window; reboot on the new model family
date: 2026-06-09
status: superseded-by-05
supersedes: null
superseded_by: 05-multiball-reboot-default-on
commits: [8ea452b]
---

# Abort the multiball default-ON window; reboot on the new model family

> **Superseded 2026-06-17 by [ADR-05](05-multiball-reboot-default-on.md).** All four reboot conditions defined below were met, and multiball was re-armed default-ON at N=5. This record stands as the abort rationale and the conditions that gated re-arming.

**Decision**: Abort the 2026-06-07 multiball default-ON N=5 experiment immediately (was set to expire 2026-06-21). Multiball reverts to opt-in (`--multiball[=N]`, bare default N=3). The experiment reboots later, on the new model family, with its analyzer built first. **[Update 2026-06-17: rebooted at N=5 default-ON per [ADR-05](05-multiball-reboot-default-on.md) — all four conditions below resolved. The "reboots later" state is no longer pending.]**

**Why**: Two independent reasons, either sufficient.

1. **Zero adjudicable data accrued.** The experiment's decision procedure requires `within_persona_runs` snapshots plus a subsample-N analyzer. Two days into the 14-day window: all three post-flip run dirs are missing `findings-snapshot.json` AND have empty `findings/` — the exact run-record regression SKILL.md §4 warns against — and the analyzer was still "deferred" (backlog). On that trajectory the window expires with nothing to decide on, having burned 5× per run for nothing. [ran: inspected `~/.angel/runs/2026060{7,8,9}T*`; read: backlog.md:16]
2. **The model family changed mid-window (2026-06-09).** The N=5 rationale rests on ~40% Important+ test-retest reproducibility measured on the 4.x family (recurrence-pilot). The session default is now `claude-fable-5`; the 4.x numbers are of unknown validity for the new family, and data collected now would calibrate a superseded configuration. If new-family per-pass recall is higher, the optimal N drops — possibly to 1 — making N=5 data on the old family doubly wasted.

**Rejected alternative**: Ride out the window to 2026-06-21 while fixing the data-capture regression. Dropped: even with capture fixed, ~9 remaining days of old-family data answers a question we no longer need answered; the marginal information does not justify 5× run cost.

**Reboot conditions** (re-flip default-ON only when ALL hold):
1. The subsample-N analyzer exists and passes its own tests (extend `scripts/recurrence-pilot.py` per backlog).
2. New-family models are dispatchable to persona subagents. **MET 2026-06-12** [ran: tier self-report probes]: the Agent tool's coarse tiers are `haiku|sonnet|opus|fable` and resolve to `claude-haiku-4-5-20251001` / `claude-sonnet-4-6` / `claude-opus-4-8[1m]` / `claude-fable-5[1m]` — the new family IS dispatchable, and this condition's original premise (tiers pin to 4.x/200k) was wrong. Caveat: probed from a `[1m]` parent session; resolution may inherit that — which is the configuration /angel actually runs in.
3. The recurrence pilot has been re-run on the new family to set the experiment's N (don't assume 5).
4. Run-record completeness is enforced mechanically (e.g., a finalize step gating on `check-run-complete.py`), so the data-capture regression that killed this window cannot silently recur.

**Could-be-wrong-if**: the new family's per-pass reproducibility turns out ≈ the old family's ~40% AND new-family persona dispatch remains unavailable past ~2026-Q3 — then old-family N=5 data would have retained decision value and aborting cost us a window. Check: when reboot condition 3 runs, compare new-family Important+ recurrence to 40%; if within ±5 points and condition 2 is still blocked, this abort was premature (cheap to accept — the experiment re-arms whenever conditions clear).

**How to apply**: SKILL.md §1 flag lines + §4 Multiball section reverted to opt-in (this commit). DESIGN.md experiment paragraph and backlog item marked aborted. Reader-calibration auto-trigger does NOT resume at revert — it was removed separately per docs/decisions/01 (the §1.6 "auto-restores at expiry" note is void).
