# Contributing to NineAngel

Thanks for considering a contribution. NineAngel is a personal tool used in production by the author; pull requests for bug fixes, prompt sharpening, and new personas are welcome.

## Adding a persona

A new persona must:

1. **Live at `personas/<filename>.md`** (the filename need not match the short name — see the "Persona file" column in SKILL.md §1 for the existing short→filename mapping convention; choose a descriptive filename and register it in both mapping tables) and start with YAML frontmatter:

   ```yaml
   ---
   name: <short>
   default: opt-in           # yes | opt-in; use opt-in on entry (experimental:true blocks auto-include anyway)
   modes: [diff, full]       # diff | full | [diff, full]
   experimental: true        # true on entry; drops once calibrated
   requires:
     any_of: [signal1, signal2]   # or [any] to match every project
   context:
     digest: yes             # yes | no
     project_claude_md: yes  # yes | no
     full_bundle: no         # yes | no (yes only for blindspot-style whole-repo reads)
     lane: |
       Describe the slice of the project the persona should read: entry points,
       modules touching its concern, relevant config. Keep it concise — one short
       paragraph. Orchestrator substitutes this into the dispatch prompt.
   ---
   ```

2. **Include the standard sections**: `## Your goal` (one paragraph), `## Your perspective`, `## What you're looking for`, `## Examples` (at least one flag-this and one don't-flag-this), `## How to work` (numbered steps), and `## What you are NOT looking for` (naming sibling personas whose lanes the new persona must not cross). Lane discipline is what makes the integrator's dedup phase tractable.

3. **Be marked `experimental: true` on entry.** Graduation criteria are in `DESIGN.md` (§Experimental personas): ≥5 live runs across diverse projects, false-positive rate <30% per Coach review, no systematic scope violations.

   **The one sanctioned exception: a domain angel** (a persona reviewing against an organization's written rules rather than against craft — ADR-15). It may ship `experimental: false` / `default: yes` when **all** of these hold, and the ADR that introduces it must say so explicitly:
   - it is gated by a **project-scoped signal** in `requires.any_of` that bounds it to the organization's work, and that signal is exempt from `--all` / `PERSONAS: all` bypass;
   - a **demotion falsifier** with a numeric threshold and a named, *computable* instrument replaces the proving period the opt-in entry would have provided;
   - its rules come from a registry it reads at dispatch, not from the prompt, so it is **skipped rather than run blind** when the registry does not resolve.

   The rationale is specific to this class and does not generalize: a domain angel exists because a written rule went unapplied while readable, so a reviewer you have to remember to name is the gate that already failed. Every other persona still enters opt-in. `orgpolicy` is the precedent; ADR-15 describes the pattern.

4. **Add a row** to the SKILL.md (§1) and unattended.md (Step 3) mapping tables — short name, persona file, model assignment.

   If the persona needs an orchestrator-composed context block — input that lives outside the repo, like a registry or a rendered artifact — document it on **both** paths and add it to `DISPATCH_BLOCKS` in `scripts/validate-personas.py`. That prose sits outside every mapping table, so nothing else catches a block added to one orchestrator and not the other, and the persona runs blind on the path that lost it.

5. **Update DESIGN.md** §Personas with a one-paragraph description and the persona's required signals.

6. **Before submitting**, run both gates and confirm they exit 0:
   ```bash
   python3 scripts/validate-personas.py
   bash scripts/test_scripts.sh
   ```
   Or install the pre-commit hook so both run automatically on every commit:
   ```bash
   ln -s ../../scripts/pre-commit.sh .git/hooks/pre-commit
   ```

A new persona earns its slot when it surfaces ≥1 Important+ finding across multiple live runs that an existing persona missed. If 2 of 3 calibration runs return zero unique-and-grounded findings, recalibrate or remove the persona.

## Adding a signal to the trigger vocabulary

Signals are defined in `SKILL.md §1.5` and `unattended.md §2.5`. Both tables must stay in sync. To add a signal:

1. Define it in both tables with the same detection rule (file globs, dir presence, content match).
2. Reference it from the relevant persona's `requires.any_of` list.
3. Update DESIGN.md §Battery selection if the signal affects battery sizing in a non-obvious way.

Prefer reusing existing signals over inventing new ones. The vocabulary deliberately stays small.

## Bug fixes and prompt improvements

PRs that fix bugs, sharpen prompts, or improve a persona's calibration should:

- Reference the meta-review or live-run finding that motivated the change.
- Avoid touching unrelated personas in the same PR (one persona per PR keeps the diff focused).
- Update `DESIGN.md` if the change affects architecture, selection logic, or persona-lane boundaries.
- Add a CHANGELOG entry under `[Unreleased]` for user-visible changes (new flags, persona additions/removals, default-battery changes, breaking changes to the fix-batch format or selection logic).

## Publishing / mirroring to PropterMalone

Before staging or publishing to the public mirror, both guards must be green:

```bash
bash scripts/pre-commit.sh
```

This runs `validate-personas.py` (registry consistency, frontmatter contract, signal parity) and `test_scripts.sh` (script behavior). A red suite or validator error must be fixed before the publish step — both were green at the last published HEAD.

If either guard fails, do not publish. Fix the failure, re-run, and only proceed when both exit 0. This is how the 07-20 red-suite publish happened: no pre-publish gate ran.

## Code of Conduct

By contributing, you agree to abide by the Contributor Covenant (see `CODE_OF_CONDUCT.md`).

## License

By contributing, you agree that your contributions will be licensed under MIT (see `LICENSE`).
