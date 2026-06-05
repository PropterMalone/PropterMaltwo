---
id: NN-slug
name: <short title>
date: YYYY-MM-DD
status: active
supersedes: null
commits: []
---

# <Title>

**Decision**: <one sentence describing what was decided>

**Why**: <motivation, constraint, prior incident, stakeholder ask. The thing future-anyone needs to know to understand why this isn't trivial>

**Rejected alternative**: <one option considered and dropped, with the reason it was dropped>

**Could-be-wrong-if**: <concrete falsifier — observation that would invalidate this decision. Hostile reader can identify (a) what to observe, (b) how to check, (c) threshold>

**How to apply**: <when this decision binds future work — which code paths, which kinds of changes, which scenarios>

---

## Template usage notes (delete this section in actual ADRs)

- `id`: zero-padded sequence (`01`, `02`, ...). Stable forever; new ADRs append.
- `status`: `active` | `superseded` | `rejected` | `draft`. When superseded, set `supersedes` on the new ADR pointing at the old `id`.
- `commits`: list of commit SHAs that implement the decision. Optional but valuable.
- Body sections are required for `active` status. Skip "Rejected alternative" if there genuinely was none considered (rare — if so, you probably haven't thought hard enough).
- Keep the whole file under one screen. If it's longer, it's not a decision record — it's a design doc; put it elsewhere and link.
- Falsifier blocklist: avoid "unforeseen", "edge cases", "if assumptions are wrong". One concrete falsifier > three vague ones. See `~/.claude/rules/quality.md`.
