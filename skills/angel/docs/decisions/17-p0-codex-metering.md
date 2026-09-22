---
date: 2026-08-18
status: accepted
supersedes: null
---

# P0 Codex dispatch adapter and meter classification

> **Amended by ADR-20.** Reducer usage is recorded through the backward-compatible integrator phase with typed runner and context fields when available. The token-kind warning below remains active.

**Decision**: Admit a narrow Codex dispatch adapter that can run one leaf review leg, persist its output through the existing pass-file chokepoint, and record backend-specific usage without pretending it is comparable to Agent-tool usage.

## Adapter contract

- Pin the intended executable explicitly rather than relying on ambient PATH.
- Read prompt stdin to EOF before launching the CLI, then close the child's stdin.
- Run in the target project with the same leaf-agent and untrusted-content constraints as the Claude path.
- Require parseable structured output and durable pass artifacts; exit code alone is not success.
- Record requested and actual model identity plus `backend: codex`.
- Preserve failures rather than silently replacing the leg with another backend.

## Meter classification

Codex CLI `tokens used` is cumulative uncached token usage for the session. Claude Agent-tool `total_tokens` is a peak single-turn context measure. These are different kinds. Never sum or compare them as if they were one cross-backend total; preserve backend and meter kind in every aggregate.

Re-check the Codex identity against rollout components on future CLI changes. If it no longer matches, reclassify the meter before trusting reports.

## Hardening

- Pin the intended executable explicitly rather than relying on PATH.
- Read prompt stdin to EOF before launching the CLI and close the child's stdin.
- Treat parseable output and durable artifacts—not exit code alone—as success.

## Deliberately out of scope

Backend-specific guard parity and routing-tier indirection require separate admission work. A compatible adapter is not evidence of safety or quality parity.
