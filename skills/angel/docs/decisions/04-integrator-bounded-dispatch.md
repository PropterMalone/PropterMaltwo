---
id: 04-integrator-bounded-dispatch
name: Pin the integrator off the volatile default model and bound its dispatch
date: 2026-06-10
status: active
supersedes: null
commits: []
---

# Pin the integrator off the volatile default model and bound its dispatch

> **Partially superseded by ADR-20 (2026-08-30).** Reducer-era runs use a qualified isolated reducer and deterministic-union fallback. The bounded-integration requirement remains active.

**Decision**: Integration must use an explicitly selected capable model/runner and a mechanical deadline. It must never inherit a volatile session default or wait indefinitely. Terminal failure must yield a visible fallback rather than silence.

**Why**: Integration is a lone load-bearing stage after reviewer work completes. An unbounded stall can withhold the entire report, unlike a failed persona leg, which degrades locally.

**Rejected alternatives**: Relying on provider stability or prose-only timeout instructions leaves the failure unbounded. Dropping to a smaller context tier can truncate large integrations.

**Could-be-wrong-if**: A qualified route cannot hold the required workset or repeatedly stalls despite mechanical bounds; then the workset or runner design must change rather than weakening the bound.

**How to apply**: ADR-20 supplies the acting route. Preserve explicit admission, watchdogs, and visible deterministic degradation on every integration path.
