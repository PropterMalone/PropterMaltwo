---
id: 01-portable-core-thin-host-adapters
name: Portable core with thin host adapters
date: 2026-09-26
status: active
until: null
amends: null
supersedes: null
commits: []
depends_on: []
falsifier_cmd:
  - {label: adapter-contract, cmd: "python3 -m unittest tests.test_adapter_contracts -v"}
  - {label: docs-admission, cmd: "python3 -m unittest tests.test_portability_adr_admission_consistency -v"}
applies_to: ["adapters/**", "manifests/**", "docs/hosts/**", "docs/portability-admission.md"]
---

# Portable core with thin host adapters

**Decision**: Keep one portable doctrine/canonical-skill source, add only thin
host-coupled adapters, and admit every installed artifact and capability through
the versioned host manifest.

**Why**: Independent copies drift, while pretending every Claude workflow ports
to every host creates unsafe paper parity. Separate host namespaces let Codex
and Polytoken share content without destination collisions or hidden runtime
dependencies. The manifest makes exclusions and maturity testable.

**Rejected alternative**: Copy the complete Claude tree into each host and patch
it locally. That duplicates canonical bodies, carries Claude/Anthropic state
into independent hosts, and turns unsupported integrations into implied support.
A wholesale repository move was also rejected because it would break the legacy
Claude installation surface without improving this milestone's adapters.

**Could-be-wrong-if**: This structure should be replaced if either contract test
finds a duplicate/extra adapter artifact or docs diverge from the manifest, or if
a first-class host cannot retain its admitted instruction, skill, memory,
subagent, hook, permission, doctor, and rollback floor without copying canonical
bodies.

**Evaluated by**: the two `falsifier_cmd` entries above, verbatim →
`[ran 2026-09-26]`: adapter-contract exits 0 when the adapter tree equals the
frozen set and lifecycle/dependency contracts hold; docs-admission exits 0 when
the ledger, host docs, and manifest agree.

**Status quo check**: Before this decision, the repository had no `adapters/`
source tree, host manifest, or host documentation, so both commands failed by
missing modules/artifacts. That does not meet the acceptance threshold.

**How to apply**: Add a host feature only by changing manifest admission, source,
tests, and docs together. Prefer canonical portable content plus a minimal host
loader. Keep machine-specific verification, accounts, private paths, billing,
and telemetry outside the repository. A local skipped smoke changes activation
evidence only; it never mutates static support.
