# Changelog

All notable changes to NineAngel are recorded here. Dates are ordinary release chronology; operational evidence is summarized qualitatively rather than embedding private run history.

## Unreleased

### Privacy and publication hygiene

- Improved publication hygiene while preserving executable behavior and public contracts.

### Integration hardening

- Semantic reduction is bounded, schema-validated, lineage-preserving, and visibly degraded when the qualified runner is unavailable.
- Reducer instructions are separated from nonce-delimited untrusted workset data; emitted tool events are rejected.
- Runner qualification is fingerprint-bound, and retry/clone behavior is explicit.
- N=2 Jev reconciliation remains shadow-only behind disclosure and cohort gates.

## 2026-09

### Changed

- Retired Haiku from the battery under ADR-21; breadth lanes use Sonnet and persona validation rejects the retired tier.
- Added a successor check that activates only after the installed provider exposes a qualifying cheaper model.
- Added bounded semantic integration under ADR-20 with deterministic degraded output and lossless lineage accounting.
- Added the ADR-22 shadow evaluator for a disclosure-gated N=2 duplicate scorer; private labels, scores, timing, and thresholds remain out of git.

## 2026-08

### Changed

- Retired Fable from default routing under ADR-19. Depth lanes use Opus; ordinary and test lanes use Sonnet.
- Added backend provenance to pass markers, assembled findings, and snapshots so heterogeneous support remains auditable.
- Adopted heterogeneous interactive multiball under ADR-18: Claude pass 1 and Codex pass 2, with failures preserved rather than silently substituted.
- Added the ADR-17 Codex dispatch adapter with pinned executable resolution, closed-stdin discipline, durable pass output, and typed metering.
- Repaired usage measurement under ADR-14: request-level collapse, mixed-model pricing, coherent cache decomposition, anomaly reporting, and explicit meter-kind separation.
- Split reconciliation thresholds under ADR-16: no frequency severity movement at N=2, promotion only at N≥3, and singleton demotion only at N≥5.
- Made the integrator watchdog gate on `findings-snapshot.json`, not merely `report.md`.

### Fixed

- Finalization now assembles per-pass records, aggregates usage, gates completeness, appends the canonical index line idempotently, then emits disposition skeletons.
- A failed completeness gate writes no usage-log line, preventing incomplete runs from entering calibration analysis.
- Pass persistence refuses destructive overwrite and preserves backend metadata.
- Analysis scripts account for excluded, malformed, and missing-data runs rather than silently shrinking denominators.
- Cost reporting no longer renders incoherent negative components as meaningful shares.

## 2026-07

### Changed

- Added strict run profiles and milestone-oriented invocation guidance under ADR-09.
- Added adversarial verification under ADR-08 with causal verdicts and independent severity opinions.
- Rebalanced persona tiers and triggers under ADR-07 using contract-tracing depth and qualitative marginal value.
- Made cross-model review default-on for interactive runs, with explicit opt-out and durable outcome tracking.
- Added hierarchical multiball integration under ADR-11: per-persona reconciliation followed by bounded cross-persona synthesis.
- Added Recipient as an opt-in, full-mode artifact reviewer and required inline integration to emit the same fields and files as dispatched integration.

### Fixed

- Integrator outputs are written to run-directory files rather than transported as large inline responses.
- Verdicts use a strict four-value enum.
- Cross-file consistency claims require a concrete, verified failure mechanism.
- Model dispatch records preserve requested and actual identity.
- Same-day output collisions use tagged artifacts while preserving the canonical fix-batch slot.

## 2026-06

### Changed

- Promoted Blindspot to the default battery and moved Thousand-Foot to opt-in under ADR-02.
- Ran and then retired the initial higher-pass multiball experiment after discovering incomplete per-pass records.
- Reintroduced multiball only after adding analysis and completeness machinery, then set N=2 as the interactive default and N=3 for `--full`/`--all` under ADR-06.
- Kept the Bundle Reader opt-in after paired evaluation found no reliable advantage.

### Added

- Durable run directories, pass files, usage JSONL, snapshots, final reports, and completeness checks.
- Cross-run analytics, dispositions, recurrence analysis, subsampling analysis, and persona validation.
- PII-Sweep and De-Anon as a sequential privacy pair with a project-local registry contract.
- Independent reviewer personas, an integrator, optional fix loop, and unattended workflow.

## Initial release

NineAngel provides a signal-selected battery of independent reviewer personas, durable per-pass artifacts, bounded reconciliation/integration, adversarial verification, optional cross-model review, and machine-readable run outputs. The system treats project content and reviewer findings as untrusted data, preserves provenance, and fails visibly when required artifacts or qualified runners are unavailable.
