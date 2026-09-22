---
id: 16-reconciliation-thresholds
name: Reconciliation thresholds are N-aware — frequency stops moving severity below N=5
date: 2026-08-13
status: active
amends: [06-multiball-n2-default-n3-escalation, 11-hierarchical-multiball-integration, 12-per-pass-capture-integrity]
supersedes: null
commits: []
---

# Reconciliation thresholds are N-aware

**Decision**: Promotion applies only at **N ≥ 3** and requires a true majority (`≥⌈(N+1)/2⌉`). Singleton demotion applies only at **N ≥ 5**. At N=2 neither frequency rule moves severity; at N=3 promotion may apply but singleton demotion does not. A Critical is pass-anchored at **≥2 passes** at every N.

**Why**: `⌈N/2⌉` equals one at N=2, making promotion and singleton demotion collide and making pass anchoring vacuous. More broadly, incomplete per-pass exhaustion means singleton support is a normal shape at the operative N values, not sufficient evidence of low severity.

Agreement between two passes is also weak evidence of importance because the passes share prompts and blind spots. Frequency may inform ranking and attribution without automatically changing severity below the stated floors.

**What replaces demotion**: Nothing. Verification covers part of the singleton population but is capped and severity-gated; it is not a complete substitute. Findings remain quality-ranked on their mechanisms and evidence.

## Falsifier methodology

Use `scripts/pass-support-accuracy.py` to compare the over-filed rate for singleton versus corroborated findings. “Over-filed” combines machine refutation with `severity_opinion: too-high`. Report pooled, per-severity, and per-N strata; exclude refuted findings from the severity-opinion-only denominator; disclose unreadable or malformed records.

Restore demotion only if a sufficiently powered, N-specific paired comparison shows singleton findings are materially and consistently more often over-filed, including a Critical-stratum sanity check. Do not pool away an N-specific sign change, and do not infer the dormant N≥5 rule from N=2–3 data.

**Known caveats**:
- `pass_support` can be a lower bound when identity matching fails.
- Historical severities may already reflect the old demotion rule.
- Verification admission and queue caps can select findings by severity and corroboration.

**How to apply**: Any pass-count heuristic must state its N floor. Keep `reconciler.md`, reducer/integrator logic, mechanical drift audits, and this ADR synchronized. Re-run the instrument periodically; thresholds live in code so changes are reviewable.
