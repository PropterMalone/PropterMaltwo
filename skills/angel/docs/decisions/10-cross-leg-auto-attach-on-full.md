---
date: 2026-07-15
status: superseded-in-part
supersedes: null
superseded_note: "The cross-model leg was later made default-on for every interactive run, not only --full/--all. The measurability enhancements remain active; only the narrower trigger is superseded."
---

# Cross-model leg auto-attaches to high-leverage reviews

**Decision**: Attach the cross-model review leg automatically to `--full` and `--all` runs, with an explicit `--no-cross` escape hatch. Later policy broadened the default to all interactive runs.

## Why

The main battery shares a model family and can therefore share blind spots. A separate backend adds a genuinely different error surface. Earlier observations were not sufficient to estimate a stable hit rate because runs were inconsistently attached and their outcomes were not dispositioned, so the decision also makes the leg measurable:

- log whether an Angel report was available to the cross leg;
- assign stable finding IDs;
- record cross-finding dispositions;
- preserve backend identity and failures rather than silently substituting.

## Re-evaluation bar

Drop or narrow the leg if a consecutive paired cohort yields no accepted findings Angel missed and no correct refutations of Angel, or if the extra wall time and failure rate outweigh its contribution. Pin the reliable backend if one route is materially less dependable.

**Rejected alternative**: Decide from a small, unpaired corpus. Without consistent attachment and dispositions, absence of recorded wins is not evidence of no value.
