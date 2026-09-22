---
date: 2026-08-26
status: accepted
depends_on:
  - ref: angel:07
    claim: model tiers follow contract-tracing depth and require verified identity
  - ref: angel:14
    claim: unlike meter kinds and incomplete outcomes cannot support precise cost-effectiveness claims
---

# Retire Fable from the battery

**Decision**: Remove Fable from every default persona, reconciler, integrator, and verifier route. Move depth lanes to Opus and ordinary/test lanes to Sonnet. Keep `--model-override fable` only as an explicit compatibility escape hatch while the platform supports it.

## Why

The tier added cost and operational complexity without sufficiently reliable evidence that it improved accepted review outcomes. Historical comparisons were confounded by trigger changes, model-family changes, missing dispositions, and incompatible meter kinds. Those data can motivate caution but cannot justify a precise value claim.

Retirement simplifies the acting path:

- one strong tier for deep causal tracing and synthesis;
- one volume tier for concrete bug-catching and tests;
- no availability ladder whose fallback silently changes review depth;
- fewer tier aliases and less drift across interactive and unattended tables.

## Instrumentation

`scripts/depth-lane-yield.py` compares accepted unique findings within runs while preserving model identity and accounting for excluded runs. It is a falsifier for the retirement, not a backward proof. Synthetic fixtures validate accounting but are not evidence of live quality.

## Reopen condition

Reconsider a third tier only after a predeclared, model-verified, dispositioned cohort shows material unique Important+ contribution at an acceptable cost and failure rate. Changing control-arm persona membership or triggers invalidates the baseline and requires a new cohort.

**Rejected alternative**: Keep Fable on a small subset based on pooled historical yield. Pooling across changing rosters and incomplete dispositions would preserve complexity without a defensible denominator.

**Confidence**: Moderate and explicitly inferential. The measurement layer can test the decision going forward; historical operational vectors are not retained here.
