---
globs:
  - "**/*"
---
# Shared Project Glossary (v0.1)

Canonical meanings for terms used across projects. A project glossary inherits this file and adds
only domain-specific terms or explicit refinements.

This Markdown file is the source of truth. If you later build tooling that derives a term index — a
crawler, a semantic graph, a generated consumer view — that tooling reads from here and never
supersedes it until a reviewed migration says otherwise.

<!-- adapt: the entries below are the general-purpose set. Keep the composition rules; add,
     remove, or narrow terms to match the vocabulary your own projects actually argue about.
     The test for inclusion is in rule 5: does the term constrain a decision or expose a bug? -->

## Composition rules

1. Use a shared term unchanged when the concept is the same.
2. A project may narrow a shared definition, but must name the refinement and preserve every shared
   invariant.
3. If a project needs a contradictory meaning, choose a different term. Never redefine silently.
4. When the same local term appears in a second project, promote the common meaning here and replace
   local copies with pointers or refinements.
5. Add terms that constrain decisions or expose bugs. Do not grow this into a general software
   dictionary.

Each entry should provide a definition, a boundary (`Not`), and an observable consequence or
invariant when one exists.

## Phase 0

The terminology pass before architecture or implementation. It records the load-bearing nouns,
states, and boundaries needed to reason about the project.

Not: a complete requirements phase or an excuse to delay a reversible spike.

Invariant: unresolved disagreements about a term remain explicit; implementation does not silently
choose a meaning.

## Source of truth

The one canonical mutable artifact for a fact or decision. Indexes, dashboards, summaries, and
caches may point to or derive from it.

Not: every copy that happens to contain the same value.

Invariant: update the source first; derived copies never outrank it.

## Invariant

A condition that must hold throughout the scope in which it is declared.

Not: a preference, expected tendency, or goal.

Invariant: a hostile reader can identify an observation that would prove it false.

## Gate

A declared condition that must pass before a transition or action is allowed.

Not: advice, a warning, or an uncalibrated score presented without a threshold.

Invariant: failure stops or diverts the transition; it cannot merely annotate continued execution.

## Bounded

Constrained by explicit finite limits appropriate to the operation, such as candidates, bytes,
requests, steps, elapsed time, or permitted actions.

Not: `small`, `reasonable`, or another qualitative promise.

Invariant: the applicable limits can be named before the operation starts.

## Observation

Evidence gathered without intentionally changing the target system's state or advancing its
workflow.

Not: an operation called read-only solely because its side effects are expected to be harmless.

## Candidate

One member of an explicit finite set eligible for selection under stated constraints.

Not: an unconstrained generated answer.

Invariant: selection returns a member of the set or abstains.

## Proposal

A recorded recommendation for a candidate or action that has not been executed or authorized by
the proposal itself.

Not: proof that the action is safe, correct, or permitted.

Invariant: downstream code cannot infer execution from the presence of a proposal.

## Abstention

An explicit result that declines to select or act because the available evidence or constraints do
not support one valid choice.

Not: an error, timeout, empty string, or silently missing result.

## Action

An operation applied to a target system to change its state or advance its workflow. Navigation and
UI interaction count even when no durable server mutation is expected.

Not: observation, reasoning, or a proposal.

## Postcondition

An observable predicate checked after an action to determine whether the intended state was
reached.

Not: the action returning without an error.

## Dry run

A validation or simulation path that describes or checks intended work without committing its
target effects. It may replace live inputs or skip live decision paths.

Not: a synonym for shadow mode.

## Shadow mode

A run that uses the real observation and decision path, records the action it would propose, and
suppresses target-system actions. Local reports and telemetry may still be written.

Not: guarded execution, execution followed by rollback, or a dry run that skips the live path.

Invariant: every target action remains unexecuted and is represented only as a proposal.

## Stub

The minimum durable project shell: a stable identity, scope boundary, source-of-truth location, and
next decision or action. A stub may be unbuilt or may contain an early prototype.

Not: a claim that the project has working behavior.

## Prototype

A working implementation built to test named uncertainties before its API, reliability, or
operational guarantees are fixed.

Not: production software with weaker branding.

Invariant: the uncertainty being tested and the evidence needed to resolve it are recorded.

## Calibration

Measurement of a score or decision rule against labeled outcomes from the population and action
class where it will be used.

Not: a smoke test, a handful of successful examples, or the model's stated confidence.

## Data class

A declared handling category based on the data's sensitivity and provenance. Each project defines
the classes it supports.

Not: permission to collect, transmit, or automate a source.

## Source authorization

The recorded basis for using a source in the proposed way, evaluated independently from its data
class and technical accessibility.

Not: an inference that public visibility, successful login, or browser access grants automation
permission.
