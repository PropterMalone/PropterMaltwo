---
date: 2026-06-17
status: superseded
supersedes: 03-multiball-abort-family-reboot
superseded_by: 06-multiball-n2-default-n3-escalation
---

# Multiball rebooted after instrumentation and family checks

**Decision**: Re-enable multiball for interactive `/angel` runs after the ADR-03 reboot conditions were satisfied. The reboot used a higher pass count temporarily so the analyzer could observe a usable subsampling curve; ADR-06 later replaced that setting with N=2 by default and N=3 for `--full`/`--all`.

## Why reboot

The first experiment was not adjudicable: required per-pass records were incomplete, the subsample analyzer did not yet exist, and the model-family configuration changed during the window. Re-enabling before those conditions were repaired would have produced more cost without interpretable evidence.

The reboot conditions were:

1. `scripts/subsample-analyzer.py` exists and is covered by synthetic tests.
2. The active model family is verified at dispatch.
3. The recurrence prior is applicable to the active family, or is re-derived before use.
4. Run-record completeness is mechanically enforced by `init-run.sh`, `finalize-run.sh`, and `check-run-complete.py`.

## Cost model

Staggering later passes can improve input-cache reuse, but it does not cache independently generated output. N passes still produce roughly N times the output work. The pass count is therefore a budget choice constrained by marginal review value, not a free reliability knob.

## Tune-down rule

The higher-pass reboot was always temporary. Once enough complete runs existed, `subsample-analyzer.py` was to compare lower-N projections and choose the lowest N that retained most distinct Important+ findings. In practice the reboot window still did not produce a trustworthy curve, so ADR-06 adopted the cost-minimizing 1→2 prior and retained an N=3 escalation for higher-leverage full runs.

**Could-be-wrong-if**: Complete, adjudicated data later shows N=2 misses materially more unique Important+ findings than N=3 or a higher pass count. In that case amend ADR-06 with the measured curve and an explicit budget trade-off.
