---
id: 06-multiball-n2-default-n3-escalation
name: Multiball default N=2 interactive, N=3 escalation on --full/--all
date: 2026-06-20
status: active
supersedes: 05-multiball-reboot-default-on
commits: []
---

# Multiball default N=2 interactive, with N=3 escalation

**Decision**: Multiball is **default-ON at N=2 for interactive `/angel`**, effective 2026-06-20. It **escalates to N=3** automatically when `--full` or `--all` is passed, and on demand via `--balls N` (or `--multiball=N`); an explicit override always wins over the auto-escalation. `--no-multiball`/`--single` forces single-pass. Unattended (`claude -p`) stays single-pass. This supersedes ADR-05 (N=5 starting point).

**Why**: The intended saturation curve was not usable because early per-pass records lacked the structured shape the analyzer requires. The higher provisional N therefore had no measured recall justification. N=2 preserves the highest-value resampling step while limiting extra generation; N=3 is reserved for broader or explicitly escalated reviews.

This is a prior, not a result: persona output is materially stochastic, but the exact point where returns flatten must be learned from properly recorded current-family runs.

**Recording requirement**: `check-run-complete.py` must reject a multiball run whose snapshot lacks well-formed `within_persona_runs`. The finalization gate therefore makes future tuning data either complete or visibly failed rather than silently unusable.

**Could-be-wrong-if**:

- Measurable subsample curves show N=2 repeatedly leaves material recall available at N=3: raise the default.
- Curves show the second pass adds negligible value: reconsider default-on multiball rather than paying for a no-op.
- Operational resource pressure remains disproportionate: return multiball to opt-in.

These are evaluation rules, not claims about a private corpus. Apply them only after enough complete records exist for a stable comparison.

**Rejected alternatives**:

- **Keep N=5**: rejected because its measurement premise did not execute and the standing premium was unjustified.
- **Drop to N=1**: rejected because independent resampling remains the core variance-reduction mechanism.
- **Fixed N=3 always**: rejected because the third pass is better tied to broad/high-leverage runs or explicit operator choice.

**How to apply**: Update SKILL.md and public usage docs to N=2 default/N=3 escalation; enforce structured per-pass capture in finalization; leave unattended mode single-pass.
