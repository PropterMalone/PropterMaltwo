---
id: 13-inline-integration-field-parity
name: Inline integration owes the same fields, and inline verification writes its verdict files
date: 2026-07-28
status: active
amends: [08-adversarial-verify-stage, 09-run-profiles-invocation-policy]
supersedes: null
commits: []
---

# Inline integration owes the same *fields*, not just the same files

> **Mechanism superseded by ADR-20 (2026-08-30).** Inline integration no longer exists on
> the acting path. The parity requirement survives and is now structural: one deterministic
> renderer writes the report and snapshot from one validated decisions object.

**Decision**: An inline integration must render the same report **fields** a dispatched integrator does — `integrator.md`'s header block verbatim (including `Files reviewed` and `Pre-flight`), a wall-clock **duration**, the verdict **enum**, and a derived `Effort` rollup — and when it verifies findings inline it must WRITE `$RUN_DIR/verification/{id}.json` per finding before invoking `apply-verification.py`.

**Why**: File-level parity is insufficient when alternate renderers independently reconstruct the report. They can omit fields or contradict the machine snapshot. The verifier application step reads verdict files; running it without first materializing those files is a valid no-op, not a repair. A single artifact source keeps report sections, header counts, and snapshot verdicts consistent.

**Rejected alternative**: Teach `apply-verification.py` to read either verdict files or verification fields already embedded in a snapshot. Rejected because two accepted inputs recreate the divergence this decision prevents. Use one input and one renderer.

**Could-be-wrong-if**: The resulting report, verdict files, and snapshot still disagree or required header fields are absent. If prose cannot prevent that drift, enforce the contract mechanically in `check-run-complete.py`.

**How to apply**: This requirement historically bound every integration path that skipped an integrator dispatch. Under ADR-20 it is embodied by the validated decisions object and deterministic renderer. Effort is derived from tags, and finding locations remain pasteable paths.
