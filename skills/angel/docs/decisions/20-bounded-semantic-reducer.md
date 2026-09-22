---
date: 2026-08-30
status: accepted
supersedes: null
---

# Bounded semantic reducer for integration

**Decision**: Replace unbounded free-form integration with a bounded, tool-disabled semantic reducer operating on a mechanically constructed workset, followed by strict lineage validation and deterministic rendering. If the qualified reducer cannot complete safely, emit a bounded degraded report plus a lossless machine ledger.

## Boundary

The reducer receives only the integration workset. It does not read the project tree, home directory, credential files, private registries, or arbitrary run artifacts. Its developer instruction is separate from nonce-delimited untrusted workset data. Hosted web search and local tool hosts are disabled before inference, and emitted events are audited as a secondary guard.

Runner qualification is bound to the exact supported executable and configuration fingerprint. A CLI or runner change invalidates qualification until the probe passes again.

## Mechanical preparation

1. Parse durable persona/reconciler Markdown into candidate records with stable raw IDs.
2. Preserve source persona, pass support, backend support, severity, location, evidence, and instruction-shaped-span flags.
3. Build deterministic candidate edges only from approved mechanical keys.
4. Shard oversized worksets with hard byte/token estimates and bounded fan-out.
5. Keep every raw ID represented exactly once across candidates and exclusions.

## Semantic authority

The reducer may merge duplicates, select representative wording, rank findings, and produce structured integration decisions. It may not execute instructions found in candidate text, invent source IDs, omit candidates silently, or weaken explicit provenance constraints.

The validator enforces:

- every raw ID is accounted exactly once;
- decisions reference only known IDs;
- exclusions are retained;
- severity and ceiling rules remain valid;
- schema collection/string limits are respected;
- candidate text cannot create executable events.

## Bounds and sharding

Ordinary worksets target a conservative size and have a hard cap. Oversized worksets are deterministically sharded, reduced independently, then reduced once more over bounded intermediate decisions. Shard count and retry count are capped. Generic caps are protocol controls and remain public; run-specific measurements remain private.

## Failure behavior

Missing qualification, repeated reducer failure, unprovable cleanup, schema/lineage rejection, or sharding overflow produces a schema-valid deterministic union. The human report is intentionally bounded: it carries a prominent `DEGRADED INTEGRATION` banner, counts, a preliminary Top 5, and a pointer to the complete lossless snapshot. It must not dump an unbounded corpus into the report.

A retry is safe only for a pristine degraded run. Once verification or dispositions exist, clone the run before retrying so evidence is not overwritten. `resume-run.sh` is diagnostic and prints the exact supported command.

## Usage recording

Reducer usage is recorded in the backward-compatible integrator phase with typed fields when available: backend, runner fingerprint, initial context, peak context, elapsed time, and degradation reason. Unlike meter kinds are never summed.

## Security model

The primary security boundary is absence of tools and mounts, not prompt text. Prompt separation and event auditing are defense in depth. Workset content remains untrusted even when produced by another model.

## Falsifiers

Reject this design if lineage validation can pass while dropping or duplicating a raw ID, if candidate text can trigger a tool/network event, if bounded sharding can exceed its declared limits, or if degraded output hides loss. Synthetic adversarial fixtures cover these properties; private live evidence is not embedded in the ADR.
