---
date: 2026-08-09
status: accepted
supersedes: null
amends: [08-adversarial-verify-stage, 12-per-pass-capture-integrity]
---

# Repair the measurement layer before using it for policy

**Decision**: Treat usage and outcome telemetry as typed measurements with explicit identities, denominators, and failure accounting. Repair request collapse, token-kind labeling, disposition capture, and falsifier inputs before drawing routing conclusions.

## Problems found

- Transcript streams can repeat one request's usage object across multiple content-block records. Summing lines therefore double-counts some token classes.
- Trailing all-zero records can follow a real request; choosing the last duplicate can erase the request.
- Context can shrink between turns. A rewrite estimate based only on previous context can become negative or otherwise incoherent.
- Different backends expose different token measures. A cumulative uncached-token counter is not interchangeable with a peak single-turn context measure.
- Missing dispositions, missing snapshots, malformed fields, and arm-filter exclusions can silently shrink denominators.
- Verification outcomes need a severity opinion separate from the causal verdict.

## Repairs

1. Collapse transcript records by request identity, falling back to message identity when necessary; retain the representative record with real output rather than an all-zero trailer.
2. Price mixed-model transcripts per request and preserve model identity.
3. Bound rewrite by both previous and current context so decomposition components remain non-negative by construction.
4. Surface duplicate-record disagreements and out-of-order records as anomalies instead of swallowing them.
5. Refuse to render negative decomposition components as meaningful shares.
6. Keep backend totals separate and label each meter kind. Never sum unlike measures into a cross-backend total.
7. Add `severity_opinion` to verifier verdicts and `scale` metadata to usage summaries.
8. Make analysis scripts account for every iterated run in exactly one included/excluded/error bucket.
9. Seed `dispositions.json` for every finalized run so "not triaged" differs from "not observed."

## Interpretation rules

Public list prices may be used for cost estimates, but estimates must state which token classes and cache rates they price. Generic thresholds and protocol caps remain part of the decision contract; private corpus vectors and one-off fleet measurements do not belong in source.

Measurements are evidence only for the version and meter semantics that produced them. A nonzero anomaly count, model-identity mismatch, or incoherent decomposition invalidates downstream conclusions until investigated.

**Could-be-wrong-if**: Request identities are not stable enough to collapse duplicates, token-kind classification changes in a backend release, or the repaired decomposition still produces negative components on valid input. The runtime canaries and synthetic tests are the falsifiers.
