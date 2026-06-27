---
id: 02-blindspot-thousand-swap
name: Swap Blindspot↔Thousand-Foot in the default roster
date: 2026-06-06
status: active
supersedes: null
commits: [eff8cad]
---

# Swap Blindspot↔Thousand-Foot in the default roster

**Decision**: Promote Blindspot to the default battery (`default: yes`, `experimental: false`) and demote Thousand-Foot to `default: opt-in`.

**Why**: The `mine-runs.py` value analysis (47/80 parseable runs, 29 projects) ranks Thousand-Foot worst on cost/value — most expensive persona (~5.3M tokens), lowest unique high-severity yield (24 solo Important+), and its Criticals are nearly all co-attributed (rarely the sole catcher). Blindspot and Thousand-Foot are both Opus absence/architecture reasoners — the two consolidation candidates DESIGN.md already names — so they occupy the same lane. Blindspot shows strong early signal (6 solo Important+ in just 2 runs) but too little data to judge. Swapping rather than stacking removes the redundant premium-cost persona while letting Blindspot accrue the ~dozen full-run data points needed to adjudicate the lane.

**Rejected alternative**: (1) *Stack* — add Blindspot on top of Thousand-Foot. Dropped: running two overlapping Opus lanes together inflates cost and overlap and muddies attribution (a change in finding quality couldn't be cleanly assigned to +Blindspot vs. the still-present Thousand). (2) *Scrap Thousand-Foot outright.* Dropped: data is still thin — Thousand is #3 in raw Critical count, and DESIGN roster discipline says cut on precision data, not solo-volume alone. Demote-not-delete keeps it nameable (`/angel thousand`, `--all`) and recallable.

**Could-be-wrong-if**: After Blindspot has ≥~12 full-run findings-snapshots, re-running `mine-runs.py` shows Blindspot's solo Important+ rate no better than Thousand-Foot's was — concretely, ≤ ~0.53 soloI+/run (Thousand's historical 24/45) — AND (once the recurrence proxy exists) its findings don't get fixed at a higher rate. That would mean the swap traded one mediocre absence-reasoner for another rather than upgrading the lane.

**How to apply**: Binds default-battery selection on `/angel --full` runs, and — a consequence missed at decision time — on diff runs too: demoting Thousand-Foot removed the only diff-default top-tier absence/architecture reasoner, so plain diff runs now carry zero of that lane. **Correction 2026-06-12** (full meta-run finding f3): the original "diff runs are unaffected" claim was false. The diff-mode gap is consciously accepted until the review trigger (the maintainer, 2026-06-12); interim opt-in is `/angel thousand` on diff runs that want the lane. At the review trigger (≥~12 Blindspot full-runs), decide (a) Blindspot keep vs revert, (b) Thousand-Foot scrap vs re-tune. If Thousand-Foot is kept, re-tune its lane *up* to strategic direction ("is the overall approach right" — queue-not-cron, whole-module duplication) so it complements rather than duplicates Blindspot. Do not return either persona to the default stack without precision data.
