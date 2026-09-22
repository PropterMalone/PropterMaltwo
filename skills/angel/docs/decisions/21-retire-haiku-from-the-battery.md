---
date: 2026-09-12
status: accepted
supersedes: null
---

# Haiku is retired from the battery

**Decision**: No persona dispatches Haiku. The breadth lanes that previously used it now run Sonnet. `validate-personas.py` rejects `haiku` in both interactive and unattended model tables.

## Why

The supported provider lineup no longer offers a current Haiku tier that satisfies the battery's compatibility and capability requirements. Retaining a stale model ID creates dispatch drift and a false impression of a supported low-cost route. Sonnet is therefore the cheapest admitted Claude tier.

## Successor gate

`scripts/haiku-successor-check.py` is a falsifier, not an auto-migration tool. It exits nonzero only when the installed Claude Code binary advertises a model that:

1. belongs to the intended cheaper family;
2. is newer than the retired model;
3. supports the required context and dispatch surface; and
4. is available to the active account/installation.

A positive check triggers evaluation and a new ADR. It does not silently change persona tables.

## Rejected alternative

Keep the retired ID as a best-effort alias. Provider aliases can resolve differently across surfaces, so explicit unsupported IDs are safer to reject than to reinterpret.

**Could-be-wrong-if**: A qualifying successor becomes available and Sonnet's cost materially constrains breadth coverage. Run the successor check, evaluate the candidate on synthetic and private adjudicated workloads, and amend the tables only after acceptance.
