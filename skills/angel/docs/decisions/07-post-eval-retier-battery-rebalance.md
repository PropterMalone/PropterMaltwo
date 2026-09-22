---
date: 2026-07-08
status: accepted
supersedes: null
---

# Post-evaluation retiering and battery rebalance

> **Amended by ADR-19.** Fable is retired from the battery; its depth lanes now use Opus, while Test runs on Sonnet. The lane rationale remains active.
>
> **Amended by ADR-21.** Haiku is retired; breadth lanes now use Sonnet. The trigger and lane-boundary decisions remain active.

**Decision**:

1. Assign model tiers by **contract-tracing depth**: use the higher reasoning tier for lanes that require long causal chains or architectural reconstruction; use Sonnet for volume bug-catching, tests, and breadth-oriented checks.
2. Move Freshness to opt-in because its marginal value was weak in evaluation.
3. Tighten Test, Performance, and User triggers so near-universal project files do not make those personas effectively unconditional.
4. Make verdicts a strict four-value enum everywhere.
5. Require defect-level evidence for cross-file consistency claims: name the concrete failure and verify that the mechanism can fire.
6. Record `requested=|ran=` on every dispatch so provider-side model substitution is visible.
7. Have the integrator write report and snapshot artifacts to the run directory and return only a short confirmation.

## Rationale

The evaluation showed that lane shape, not prestige, should drive tier assignment. Deep contract tracing benefits from the strongest reasoning model; broad, concrete checks benefit more from coverage and cost control. Trigger tightening prevents common manifests and READMEs from selecting specialized reviewers when the relevant surface is absent.

Strict verdicts and durable file outputs are measurement-layer requirements: free-text labels and large inline returns make otherwise useful runs difficult to compare or recover. Cross-file consistency claims receive a higher evidence bar because plausible "incomplete change" stories are a recurring false-positive shape when the alleged path is never exercised.

## Minimal core

For a small code review, recommend Adversarial + Hypercritical, plus Data-Integrity when its signal is present. This is guidance, not an automatic override: profile selection remains the user's ex-ante decision.

**Could-be-wrong-if**: Adjudicated future runs show an opt-in lane consistently contributes unique Important+ findings, a tightened trigger suppresses valuable coverage, or a lower tier cannot complete the causal work required by its lane. Amend the relevant row and preserve requested-versus-actual model evidence.
