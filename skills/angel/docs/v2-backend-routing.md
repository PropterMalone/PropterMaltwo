# Backend routing v2

**Date**: 2026-08-18 · **Status**: DRAFT — design only. SKILL.md is unchanged until an accepted ADR activates a route.

## Problem

The review battery's doctrine should not depend on one provider's transient subscription allocation. Backend selection, model tiers, usage meters, failure semantics, and safety rails need explicit interfaces so a route can change without rewriting persona behavior.

The current system already has pieces of that abstraction: personas are addressed by lane, pass files are backend-neutral Markdown, reconciliation works from durable artifacts, and ADR-17 admits a narrow Codex adapter. What remains is a typed routing layer and evidence for each activatable posture.

## Principles

1. **Personas express required capability, not provider names.** A resolver maps a lane/tier to a concrete backend and model.
2. **Requested and actual identity are recorded.** Provider substitution or fallback is visible in every dispatch record.
3. **Meters are typed.** Peak context, cumulative uncached tokens, cache traffic, and billed usage are not merged into one total.
4. **Failure is durable.** A failed leg remains failed; fallback requires an explicit policy and provenance.
5. **Safety admission is backend-specific.** Filesystem/tool isolation, credential exposure, and hook parity must be qualified per runner.
6. **Quality admission is posture-specific.** A working adapter does not prove that a model belongs in a depth lane or that heterogeneous reconciliation is safe.

## Proposed routing surface

A posture selects concrete routes for:

- persona depth lanes;
- persona volume lanes;
- Stage-1 reconciliation;
- Stage-2 integration/reduction;
- adversarial verification;
- optional cross-model review.

Each route declares backend, model, meter kind, context limit, tool policy, timeout, retry/fallback policy, and qualification fingerprint. The orchestrator resolves the posture once at run start and records it in run metadata.

## Admission sequence

### P0 — adapter and metering

Admit one leaf Codex review leg behind explicit selection. Pin the executable, close stdin, require parseable output, preserve pass artifacts, and classify its usage meter. ADR-17 covers this step.

### P1 — tier indirection

Replace hard-coded provider model names in policy tables with capability tiers while retaining a resolver that expands to exact models. Validation checks tier vocabulary and resolver completeness.

### P2 — safety parity

Qualify each backend's filesystem, tool, hook, network, and credential boundaries. A route cannot activate merely because the CLI can run.

### P3 — quality qualification

Use synthetic benchmarks and private, predeclared adjudication to establish which concrete models can satisfy each lane. Publish qualitative decisions and public protocol thresholds, not private corpus vectors.

### P4 — posture activation

Activate a posture only when every route has both safety and quality admission. Persist the exact resolver fingerprint so later CLI/model changes invalidate stale qualification.

## Cross-family options

Heterogeneous multiball can reduce shared-family blind spots, but it changes the sampling model. Preserve backend support, keep ADR-16's N-specific severity rules, and evaluate union contribution plus noise before defaulting it. Cross-family verification is independently useful because the verifier is refute-oriented, but it needs the same admission checks.

The existing `--cross` leg remains separate until an accepted decision folds its function into the battery.

## Failure and degradation

- Missing route qualification: refuse activation or use the explicitly configured safe posture.
- Dispatch failure: record the failed backend/model and preserve any durable partial artifact; do not silently relabel a fallback as the requested leg.
- Meter parse failure: mark usage unmeasured without discarding the review output.
- Resolver drift: fail validation before dispatch.
- Stage-2 failure: use the bounded, lossless degraded report defined by ADR-20.

## Open decisions

- Stable tier vocabulary and where resolver configuration lives.
- Whether safety qualification is machine-fingerprinted like the reducer runner.
- Which posture is the default under each subscription state.
- What evidence promotes a new model into a depth lane.
- Whether cross-family verification replaces part of the standalone cross leg.

This document is a design sketch. Accepted ADRs remain authoritative for the acting path.
