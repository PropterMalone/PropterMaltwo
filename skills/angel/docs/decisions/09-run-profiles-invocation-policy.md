---
id: 09-run-profiles-invocation-policy
name: Run profiles (micro/standard/full) + milestone invocation policy
date: 2026-07-08
status: active
supersedes: null
commits: []
---

# Run profiles + invocation policy

> **Amended by ADR-20 (2026-08-30).** Profile selection and milestone invocation remain
> active, but `--micro` no longer integrates inline. Every profile uses the same bounded
> reducer pipeline; the small profile saves persona work, not a distinct synthesis route.

> **Amended by ADR-19 (2026-08-26).** Fable is retired, so the "full Fable complement" is now the
> full **Opus 5** complement, and the standard profile's demotion applies to **`future` only** —
> `test`'s full-profile destination is Sonnet too, making its half of the exception a no-op. The
> Fable-rationing rationale (why #4) and its falsifier are retired as unfirable; see ADR-19. The
> micro profile's inline-integration argument survives but weakens: the dispatch it saves is now
> an Opus call rather than a pricier Fable one, so inline is a convenience default more than a
> cost one. The three profiles themselves, and the milestone invocation policy, are untouched.

**Decision**: Define three named run profiles:

- **micro** (`--micro`): adversarial + hypercritical, plus data-integrity when signaled; N=2.
- **standard** (default): auto-detected battery; N=2; standard tier overrides apply.
- **full** (`--full`/`--all`): whole battery; N=3; full depth complement.

Standard/full runs occur at pre-merge, pre-ship, or public-artifact milestones over accumulated changes; mid-development checks use micro. The maintainer chooses the profile ex ante. The orchestrator may detect the battery within a profile but must not silently downgrade the profile.

**Why**: Named profiles separate review cadence from review depth. Micro provides a bounded feedback loop during development; milestone batching avoids repeatedly reviewing nearly unchanged code; full preserves broad lane coverage when stakes justify it. This turns allocation into an explicit operator choice rather than hidden per-run discretion.

The profile mechanism does not change multiball doctrine. Micro remains N=2, and changes to N depend on ADR-06's structured evaluation rather than profile-specific improvisation.

**Could-be-wrong-if**:

- Milestone reviews repeatedly surface accepted high-severity findings squarely inside micro's lanes: widen micro.
- A standard tier override demonstrably loses important absence-class findings: revert that override.
- Milestone batching creates consistently oversized reviews: shorten the interval rather than thinning the battery.
- Micro displaces required milestone reviews: treat that as policy drift, not a reason to redefine micro as sufficient for shipping.

**Rejected alternatives**:

- **Micro at N=1**: would remove the independent-resampling safeguard without adequate evidence.
- **A second whole-review harness as the routine tier**: not a targeted economy profile.
- **Orchestrator-selected profile**: reintroduces silent cost/rigor discretion; the human chooses the profile.
