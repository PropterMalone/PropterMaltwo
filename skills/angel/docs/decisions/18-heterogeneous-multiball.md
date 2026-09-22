---
date: 2026-08-22
status: accepted
supersedes: null
---

# Heterogeneous multiball

**Decision**: For interactive N=2 runs, dispatch pass 1 through the persona's configured Claude tier and pass 2 through the admitted Codex adapter. N=3 full runs add the documented third pass. Preserve backend provenance through reconciliation and integration.

## Why

Independent resampling within one model family reduces variance but not shared family blind spots. A heterogeneous second pass adds a different training and inference surface while retaining the same persona contract. The change is useful only if the system preserves which backend supported each finding and does not treat cross-backend token meters as comparable.

## Invariants

- Persona instructions, review scope, and output schema are identical across backends.
- Passes remain independent and cannot see sibling findings.
- `record-dispatch.sh` stamps backend identity in pass metadata.
- `assemble-wpr.py` derives `backend_support` per finding.
- Stage 1 may merge equivalent findings across models but cannot erase contradictions or unsupported candidates.
- A failed Codex pass is recorded as failed; it is not silently replaced by Claude.
- Backend usage remains separated by meter kind.

## Evaluation

The useful questions are union contribution, corroboration, false-positive rate, and failure rate—not raw finding volume. Evaluate on complete, dispositioned runs with provenance available. Synthetic replays can validate plumbing and formulas but do not establish production quality.

Frequency-based severity rules remain governed by ADR-16. Heterogeneity does not make N=2 agreement sufficient for automatic promotion, and a singleton from either family is not automatically demoted.

## Time-box and exit

Revisit after a predeclared cohort of complete runs. Revert or narrow the route if the second family contributes no accepted unique findings, materially increases noise, or cannot meet the reliability contract. Keep the adapter available for explicit experiments even if it leaves the default.

**Could-be-wrong-if**: Backend provenance is incomplete, the families' outputs are not semantically comparable enough for the reconciler, or heterogeneous runs perform worse than same-family resampling under adjudication.
