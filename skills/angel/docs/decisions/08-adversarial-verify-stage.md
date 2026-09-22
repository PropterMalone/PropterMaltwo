---
id: 08-adversarial-verify-stage
name: Adversarial verification stage — causal credibility for uncorroborated findings
date: 2026-07-08
status: active
supersedes: null
commits: []
---

# Adversarial verification stage (§5.7)

> **Amended by ADR-19 (2026-08-26).** Critical verifiers use `claude-opus-5[1m]`; other verifiers use Sonnet 5[1m]. Because verifier output is an evaluation instrument for ADR-16, model changes must remain attributable when interpreting later rates.

**Decision**: Add a default-ON verification stage after the integrator. The integrator (Phase 3.5) queues up to 8 findings — every Critical, singleton sub-`cited-spec` Importants, and all consistency-shaped C/I claims — and the orchestrator dispatches one **verifier** subagent per entry (`verifier.md`: refute-first mandate, run-it-preferred, read-only). Verdicts (`CONFIRMED`/`PLAUSIBLE`/`REFUTED`) are applied mechanically (`scripts/apply-verification.py`): CONFIRMED anchors a Critical regardless of corroboration; REFUTED findings stay in the snapshot as calibration data but are excluded from fix batches and surfaced first in a `## Verification` report section. `--no-verify` skips.

**Why**: Cross-file consistency claims and unsupported singletons need causal challenge, not merely another synthesis opinion. Corroboration supplies statistical support and a cited specification supplies direct support; verification targets the remaining high-impact claims. A dedicated refute-oriented pass can run a focused check and produces a machine-readable result that downstream policy can enforce.

**Targeting rationale**: Verify every Critical because it drives the run verdict, and target uncorroborated or consistency-shaped Important claims because those benefit most from an independent mechanism check. Keep the queue bounded so verification cannot become an unbounded second review.

**Could-be-wrong-if**:

- Verifiers only rubber-stamp claims and do not prevent unsupported findings from reaching triage: narrow the stage to Criticals.
- Confirmed singletons are no more useful in disposition than unverified ones: narrow the queue.
- A refuted finding later proves real: strengthen the refutation bar, including requiring an executed check where appropriate.
- Verification repeatedly dominates run resources: tighten the cap or eligibility rules.

**Rejected alternatives**:

- **Run another whole review harness**: poorly targeted; it verifies by incidental rediscovery rather than attacking named claims.
- **Ad-hoc orchestrator verification**: relies on discipline instead of an enforceable artifact contract.
- **Verify every finding**: spends unbounded effort on low-severity items.
- **Verifier inside the integrator**: mixes synthesis with independent causal checking and loses isolation.
