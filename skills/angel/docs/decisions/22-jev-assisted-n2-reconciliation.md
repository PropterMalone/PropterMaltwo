---
date: 2026-09-19
status: draft
depends_on:
  - ref: angel:16
    claim: frequency must not move severity at N=2, so a lossless raw union preserves the default run's severity inputs
  - ref: angel:20
    claim: Stage 2 already owns semantic merge authority under strict lineage validation
---

# Jev-assisted N=2 reconciliation

**Decision**: Evaluate a disclosure-gated Jev scorer as a shadow-only replacement for repeated Stage-1 Sonnet reconciliation on eligible N=2 runs. The acting path remains unchanged until a pre-registered private evaluation passes every promotion clause.

## Why

At N=2, ADR-16 forbids frequency-based promotion and singleton demotion. Stage 1 still records contradictions, support, and representative text, but Stage 2 already performs the final semantic merge. A bounded pair scorer may identify likely duplicate findings cheaply enough to reduce repeated reconciler work, provided it never receives authority to discard findings or form unsplittable shards.

## Safety and eligibility

The scorer receives only bounded finding pairs after a deterministic denial gate. Reject privacy personas, identifiers and URIs, email addresses, credential-like strings, restricted-party markers, and regulated or client-record vocabulary. Unknown or ambiguous targets abstain. Keep all labels, scores, thresholds, timing, and corpus artifacts outside git.

The shared Jev policy remains authoritative. Only explicitly approved, sanitized architecture/code/schema/synthetic-fixture content is eligible; secrets, production records, embedded user content, legal material, and sensitive operational data are not.

## Shadow contract

- The acting Sonnet reconciler continues to produce the workset.
- Jev writes only isolated shadow artifacts.
- Candidate scores cannot enter `candidate_edges` or otherwise affect sharding.
- Every raw finding ID remains represented in the alternate output.
- Evaluation registration is chronological and score-blind.
- Failures and denied pairs remain visible; no silent cohort pruning.

## Promotion gate

Promotion requires a pre-registered, consecutive, privately evaluated paired cohort with score-blind raw-ID adjudication. It must show no lost confirmed Critical/Important mechanism, no false merge of distinct high-severity mechanisms, bounded shard growth, and acceptable model-use and wall-time deltas. Publish only the cohort date/size and pass/fail verdict; keep scores, token figures, timing figures, labels, and thresholds outside git.

**Rejected alternative**: Letting Jev coalesce directly could erase a distinct defect before Stage 2. Putting scores in `candidate_edges` would grant structural sharding authority.

**How to apply**: This governs only Stage-1 reconciliation routing. Until promotion, exercise the shadow path and leave Sonnet acting.
