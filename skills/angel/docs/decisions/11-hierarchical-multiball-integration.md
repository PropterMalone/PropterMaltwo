---
date: 2026-07-18
status: accepted
supersedes: 04-integrator-bounded-dispatch
supersedes_scope: "model ladder for large integrations only; bounded dispatch remains active"
---

# Hierarchical multiball integration

**Decision**: Reconcile each persona's multiball passes before the final integrator, then run one bounded cross-persona integration. The final integrator runs alone on the strongest supported tier with a watchdog and an explicit fallback.

## Problem

Large integrations combine many raw pass outputs into one long-context synthesis turn. That shape is materially less reliable than short persona turns: it increases context pressure, output size, and exposure to provider stalls. Earlier dispatch records also lacked trustworthy per-dispatch timing, so anecdotal wall-time stories could not support precise rate claims.

## Design

1. **Stage 1 — per-persona reconciliation.** One reconciler receives only a single persona's N pass files. It emits a compact reconciled view plus pass-support metadata and contradictions. Reconciler failures are isolated per persona; the fallback is the lossless raw union for that persona.
2. **Stage 2 — cross-persona integration.** One integrator receives the reconciled views, deduplicates across personas, ranks findings, emits the report and snapshot, and writes both artifacts to the run directory.
3. **Bounded execution.** Dispatch the integrator in the background, gate completion on `findings-snapshot.json`, enforce a wall deadline, check once for a just-landed artifact, retry once when appropriate, then use the documented inline/minimal fallback.
4. **Durable timing.** `record-dispatch.sh` stamps real start/end values when available so future analysis can distinguish provider stalls from orchestration delay.

## Why hierarchical

Per-persona reconciliation reduces the final prompt without granting Stage 1 cross-persona authority. It preserves every pass, keeps contradictions visible, and gives the final integrator a smaller set of semantic units. The snapshot—not `report.md`—is the completion gate because a partial report can exist before machine-readable integration is complete.

## Failure semantics

A failed reconciler does not abort the run; its persona falls back to raw pass data. A failed final integration remains visible and recoverable. Never treat a partial `report.md` as final merely because the file exists.

**Could-be-wrong-if**: Hierarchical reconciliation drops unique findings, introduces material semantic drift, or costs more wall time than it saves. Falsify with lineage checks and paired complete runs, not raw output length.
