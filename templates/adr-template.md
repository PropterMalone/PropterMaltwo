---
id: NN-slug
name: <short title>
date: YYYY-MM-DD
status: draft
until: null       # set the day this stops binding, whenever status leaves draft/active
amends: null      # id of an ADR this one PARTIALLY revises (a clause), leaving the rest in force. Distinct from supersedes, which replaces wholesale. Tooling reconstructing current policy must walk both.
supersedes: null
commits: []
depends_on: []    # what this decision rests on; {ref, claim} entries. ref: house:NN | angel:NN | <project>:NN | NN (own dir) | mem:<slug> | mem:<project>/<slug>. The sweep writes support_lost: here when a ref dies.
falsifier_cmd: [] # {label, cmd} entries. cmd exits 0 = clean, 1 = fired, else error; stdout = observation. The sweep writes fired: here.
applies_to: []    # optional path globs this decision governs
---

# <Title>

**Decision**: <one sentence describing what was decided>

**Why**: <motivation, constraint, prior incident, stakeholder ask. The thing future-anyone needs to know to understand why this isn't trivial>

**Rejected alternative**: <one option considered and dropped, with the reason it was dropped>

**Could-be-wrong-if**: <concrete falsifier — observation that would invalidate this decision. Hostile reader can identify (a) what to observe, (b) how to check, (c) threshold>

**Evaluated by**: the `falsifier_cmd:` entries above, verbatim → `[ran YYYY-MM-DD]`: <each label, its stdout, and its exit code when the falsifier has NOT fired>

**Status quo check**: <the same commands run against existing data> → <result, and why it does not already satisfy the threshold>

> These two lines are not optional and not decorative. **Run the commands on the day the ADR ships — twice.**
>
> **Forward**, to prove the falsifier is computable at all: paste its exit code and "not yet met" output. A cmd that prints a number and exits 0 regardless is not a falsifier; the threshold belongs inside the cmd, so the sweep can act on it without a reader. An ADR whose falsifier cannot be computed from instruments that exist is unfalsifiable in practice no matter how concretely it is worded.
>
> **Backward, against the data you already have**, to prove the threshold discriminates. A forward run returns "not yet met" for a well-posed and an ill-posed threshold alike, so it cannot tell you the bar sits inside the current range. **If the status quo already passes, the falsifier is decorative** — it will read as a pass no matter what the change did. Set the threshold from the existing distribution, and prefer a *paired* comparison (same target, before vs after) over an absolute bar whenever the metric varies more between targets than between treatments.
>
> This guards against a recurring unadjudicable-trigger failure: a growing baseline makes the comparison move, required data is absent, or the command reports a value without a decision threshold. In each case the rule cannot be applied to the data that exists. Writing the evaluating command first, with its threshold inside it, makes the trigger decidable.

**How to apply**: <when this decision binds future work — which code paths, which kinds of changes, which scenarios>

---

## Template usage notes (delete this section in actual ADRs)

- `id`: zero-padded sequence (`01`, `02`, ...). Stable forever; new ADRs append.
- `status`: `draft` | `active` | `superseded` | `retracted` | `rejected`. Born `draft`; a fresh-context reader promotes to `active`. **`superseded`** = the world changed and a successor governs: set `supersedes` on the new ADR and `until:` on this one; dependents usually inherit the successor. **`retracted`** = the premise was false: set `until:`, and expect the sweep to flag every ADR whose `depends_on` names this one for a fresh look. `rejected` = a draft that did not survive review.
- `commits`: list of commit SHAs that implement the decision. Optional but valuable.
- `fired:` and `support_lost:` lines are written by the weekly sweep (`scripts/adr-sweep.py`), never by hand. The only hand edit is the retro suffix ` — adjudicated: real|false YYYY-MM-DD`. An adjudicated-real line means revise, supersede, or retract; the sweep re-flags it until you do.
- `depends_on`: name what the decision rests on, not everything it mentions. Two or three refs is typical; a decision with two independent reasons survives losing one, and the `support_lost` line will show which one went.
- Body sections are required for `active` status. Skip "Rejected alternative" if there genuinely was none considered (rare — if so, you probably haven't thought hard enough).
- Keep the whole file under one screen. If it's longer, it's not a decision record — it's a design doc; put it elsewhere and link.
- Falsifier blocklist: avoid "unforeseen", "edge cases", "if assumptions are wrong". One concrete falsifier > three vague ones. See `~/.claude/rules/quality.md`.
- Citations across repos: `house:NN` for the shared cross-project tier, `angel:NN` for the review-battery skill, `<project>:NN` for another project; bare `NN` only inside the same decisions dir, because every dir numbers independently from `01`. The lifecycle these fields drive is documented in [`docs/decision-records.md`](../docs/decision-records.md).
