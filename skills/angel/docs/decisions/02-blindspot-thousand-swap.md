---
date: 2026-06-06
status: accepted
supersedes: null
---

# Blindspot promoted to default; Thousand-Foot demoted to opt-in

**Decision**: Promote Blindspot to the default battery (`default: yes`, `experimental: false`) and demote Thousand-Foot to `default: opt-in`.

**Why**: Cross-run analysis found Blindspot contributing a stronger marginal defect-finding signal than Thousand-Foot. Blindspot also covers a distinct structural lane: missing checks, absent cleanup, unhandled branches, and other omissions. Thousand-Foot remains useful for strategic scope review, but it overlaps more with Coach and User and is better invoked deliberately.

This is a roster rebalance, not a deletion. `thousand` remains available by name and in `--all` only if explicitly requested because opt-in personas are excluded from the default battery.

**Could-be-wrong-if**: Future disposition data shows Blindspot's unique findings are mostly false positives, or Thousand-Foot consistently catches Important+ issues that no default persona finds. Revisit with adjudicated runs rather than raw finding counts.
