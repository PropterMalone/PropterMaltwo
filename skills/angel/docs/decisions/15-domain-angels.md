---
id: 15-domain-angels
name: Domain angels — reviewing against an organization's policy
date: 2026-08-13
status: active
amends: null
supersedes: null
commits: []
---

# Domain angels — reviewing against an organization's policy

**Decision**: Add personas that review against a **specific organization's written rules** rather than against craft, starting with `orgpolicy`. Each domain gets its own persona name so evaluation remains attributable. Rules live in a layered, provenance-tagged registry outside the reviewed project. `orgpolicy` ships `default: yes` / `experimental: false`, gated by `organization_policy_project` so it fires only where those rules govern.

**Why**: Two rules were missed in one engagement even though both were readable in memory: a draft would have started work before blockers were controlled, and client-confidential material was drafted to an unmanaged account. Neither was hook-catchable. Both were judgment-shaped failures where a known rule went unapplied.

The user chose `default: yes` over the normal opt-in proving period because a gate that must be remembered is the gate that already failed. The project signal confines the cost and authority to governed work; the precision falsifier below replaces the skipped proving period.

**Rejected alternative**: One parameterized `policy` persona. The evaluation instrument keys on persona name, while findings carry no domain field. Combining unrelated domains under one name would blend their precision and cost, leaving no evidence for domain-specific demotion. Sibling personas preserve that attribution without changing the snapshot schema or both integration paths.

**Also rejected**: one flat copied policy file. The authoritative rules live across project instructions and memory. The registry is an **index of checkable rule statements** pointing to those sources, not another source of truth.

## The registry

| Layer | Fires | Layer ceiling |
|---|---|---|
| `firm` | every organization-policy review | Critical |
| `user` | every review — the operator's own principles | Important |
| `client` | when that client is in scope | per rule |
| `bounty` | future version — live external status fetch | — |

**Provenance is an attribution right, not a confidence score.** `stated` permits attribution to the organization. `derived` permits only attribution to the operator's standing practice. `inferred` is raised as a question. Misattribution is itself one of the violations this reviewer catches.

**The effective ceiling is the lower of the layer and provenance ceilings.** That prevents a derived rule about firm material from being promoted into an unsupported statement of firm policy.

**Staleness downgrades to a question at 90 days.** A missing rule costs one catch; a retired rule asserted confidently erodes trust in the whole review.

**Anti-rules are first-class.** The registry may state what is not a violation because over-gating is a known failure mode. Rule IDs are deliberately absent here because this file ships publicly while the private registry does not.

**Location**: an organization-scoped directory under the gitignored project-memory tree, deliberately not the run-specific handoff directory. Each governed project's private memory directory contains `organization-policy-registry.path`: exactly one absolute registry-root path and no other nonblank lines. This explicit pointer lets multiple projects share one organization registry without making the public orchestrator infer identity from paths or prose.

**Dispatch**: resolve the pointer file, reject missing/relative/ambiguous paths and path escapes, then append a `<policy_index>` block after the `## Your Persona` tail. It carries absolute paths to the index and active modules. Never search neighboring registries and never dispatch without the block: if the registry cannot be resolved, skip and record the reason.

**`orgpolicy` is exempt from `--all`'s signal bypass.** It still requires `organization_policy_project`; otherwise an unrelated project could receive findings asserting an organization's authority where it does not apply. Registry resolvability cannot substitute for this gate because the registry is organization-scoped rather than project-scoped.

**Could-be-wrong-if**: after at least five governed-work runs and at least ten scored findings, the persona's combined wrong-finding rate exceeds 15%, or most Important+ findings duplicate a general craft persona. Either result demotes it to opt-in.

**Evaluated by**: `scripts/mine-runs.py --json`, reading `personas.orgpolicy` and `portfolio.overlap_important_plus`. Use untruncated JSON rather than the report's top-pairs table. Require at least five human dispositions before acting on the rate so a single machine verdict cannot dominate a thin sample.

**Known dependency**: the falsifier only works when dispositions are recorded. Recording dispositions on organization-policy runs is part of shipping it default-on.

## Scope shipped

Version 1 includes the `orgpolicy` persona, `organization_policy_project` signal, `<policy_index>` plumbing on both orchestrator paths, and a layered private registry. Future versions may add live status-dependent policy layers and automated registry accretion.
