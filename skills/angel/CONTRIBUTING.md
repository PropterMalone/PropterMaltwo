# Contributing to NineAngel

Thanks for considering a contribution. NineAngel is a personal tool used in production by the author; pull requests for bug fixes, prompt sharpening, and new personas are welcome.

## Adding a persona

A new persona must:

1. **Live at `personas/<short>.md`** and start with YAML frontmatter:

   ```yaml
   ---
   name: <short>
   default: yes              # or opt-in
   modes: [diff, full]       # diff | full | both
   experimental: true        # true on entry; drops once calibrated
   requires:
     any_of: [signal1, signal2]   # or [any] to match every project
   prefers: []
   ---
   ```

2. **Include the standard sections**: `## Your goal` (one paragraph), `## Your perspective`, `## What you're looking for`, `## Examples` (at least one flag-this and one don't-flag-this), `## How to work` (numbered steps), and `## What you are NOT looking for` (naming sibling personas whose lanes the new persona must not cross). Lane discipline is what makes the integrator's dedup phase tractable.

3. **Be marked `experimental: true` on entry.** Graduation criteria are in `DESIGN.md` (§Experimental personas): ≥5 live runs across diverse projects, false-positive rate <30% per Coach review, no systematic scope violations.

4. **Add a row** to the SKILL.md (§1) and unattended.md (Step 3) mapping tables — short name, persona file, model assignment.

5. **Update DESIGN.md** §Personas with a one-paragraph description and the persona's required signals.

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

## Code of Conduct

By contributing, you agree to abide by the Contributor Covenant (see `CODE_OF_CONDUCT.md`).

## License

By contributing, you agree that your contributions will be licensed under MIT (see `LICENSE`).
