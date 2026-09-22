---
date: 2026-07-22
status: accepted
supersedes: null
---

# Per-pass capture integrity is a mechanical contract

**Decision**: Persist every persona pass at dispatch time, assemble `within_persona_runs` from those durable files, and make finalization fail closed when a multiball run lacks structurally valid per-pass data.

## Problem

Multiball evidence is useful only if each independent pass survives intact. Hand-transcribing returned subagent text into the final snapshot is lossy and unauditable: pass boundaries, empty passes, support counts, and backend provenance can drift. A prose consensus string or list of finding IDs is not equivalent to the original finding objects.

## Contract

1. `record-dispatch.sh --pass N --findings` reads the returned findings block from stdin and writes `passes/{persona}-pN.md` atomically.
2. It refuses to overwrite a non-empty pass file. Retry output must use the documented retry path rather than destroy the first artifact.
3. `assemble-wpr.py` parses pass files and writes `within_persona_runs` into `findings-snapshot.json`; it also derives per-finding `pass_support` and backend support.
4. `check-run-complete.py` validates that multiball snapshots contain a mapping of personas to lists of pass arrays, and that each finding element is an object. Empty pass arrays are valid; prose strings and bare ID references are not.
5. `finalize-run.sh` runs assembly before aggregation and runs the completeness gate before appending to `usage.log`. A gate failure writes no index line.
6. `emit-dispositions-skeleton.py` runs only after the gated append succeeds.

## Why the order matters

Appending before completeness allows a failed then repaired finalization to create contradictory index records. Building `within_persona_runs` from the durable pass files makes the file system, not model memory, authoritative. The pre-append gate intentionally omits only the requirement for the usage-log line itself; the full audit requires it.

## Backward compatibility

Legacy snapshots may lack the newer schema fields. Audits may report them incomplete, but the parser must not reinterpret malformed legacy shapes as valid pass evidence. Existing synthetic fixtures remain the regression surface for accepted shapes and failure modes.

**Could-be-wrong-if**: The pass files cannot reproduce the snapshot without semantic loss, the gate rejects valid all-clean multiball runs, or finalization can append an incomplete run. The script suite pins all three cases.
