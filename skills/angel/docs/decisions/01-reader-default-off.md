---
id: 01-reader-default-off
name: Keep the Bundle Reader default-off (do not promote)
date: 2026-06-01
status: active
supersedes: null
commits: []
---

# Keep the Bundle Reader default-off

**Decision**: Keep the `/angel` Bundle Reader (`--reader`) opt-in and default-off.

**Why**: Paired evaluation found no reliable advantage from the implementation. Its bundles did not slice context aggressively enough to offset the reader stage, and quality differences were noisy rather than consistently favorable.

**Rejected alternative**: Accumulate more observations without changing the implementation. More data cannot repair the identified mechanism.

**Could-be-wrong-if**: A rewritten slicer materially reduces context while preserving Critical coverage in paired evaluation.

**How to apply**: Keep both orchestrator paths default-off. Revisit only after a slicer rewrite, using paired snapshots and per-agent metering. The conclusion is about this implementation, not the reader concept.
