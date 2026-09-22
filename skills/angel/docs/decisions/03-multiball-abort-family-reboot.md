---
id: 03-multiball-abort-family-reboot
name: Abort the multiball default-ON window; reboot on the new model family
date: 2026-06-09
status: superseded-by-05
supersedes: null
superseded_by: 05-multiball-reboot-default-on
commits: []
---

# Abort the multiball default-ON window; reboot on the new model family

> **Superseded 2026-06-17 by [ADR-05](05-multiball-reboot-default-on.md).** This record remains the abort rationale and the conditions that gated re-arming.

**Decision**: Abort the initial multiball default-ON experiment. Revert multiball to opt-in (`--multiball[=N]`, bare default N=3), then reboot on the current model family only after its analyzer and recording controls exist.

**Why**: The experiment could not answer its question. Required per-pass records were absent and the subsample analyzer was not yet available, so additional runs would consume resources without producing adjudicable evidence. A model-family transition also made the earlier recurrence estimate an unreliable basis for choosing N.

**Rejected alternative**: Continue the window while repairing capture. Rejected because evidence collected across an obsolete configuration would not establish the right default for the active family.

**Reboot conditions** (re-flip default-ON only when all hold):

1. The subsample-N analyzer exists and passes its tests.
2. The active model family is dispatchable to persona subagents.
3. A current-family recurrence pilot can inform N rather than inheriting an old-family estimate.
4. Run-record completeness is enforced mechanically, so missing per-pass data cannot silently recur.

**Could-be-wrong-if**: Current-family recurrence ultimately matches the earlier qualitative behavior and dispatch remains blocked long enough that old-family evidence would still have been decision-useful. This is acceptable: the experiment can be re-armed whenever the conditions clear.

**How to apply**: Revert the SKILL.md flag and multiball sections to opt-in, mark the experiment aborted in DESIGN.md, and keep reader calibration separate per ADR-01.
