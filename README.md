# PropterMaltwo

My actual Claude Code environment, genericized for sharing — the machinery, not
my data. It's the answer to a real question someone asked me on Bluesky: *what do
you actually put in your `.md` files?* Everything they'd found was either "load
this 50k-line file and trust me" or a vague description of what the files
supposedly do. This is the in-between: the real config, with the personal
specifics swapped for `<placeholders>` and inline notes explaining *why* each
piece is there.

If you sat down at a blank machine, this is what you'd lay down to work the way I
work. Drop it onto `~/.claude`, plug in your own data, and go.

## The thesis

Most of how I've gotten better at using Claude Code over the last year isn't my
skill improving — it's changes to this environment. The model is the same one you
have. The difference is the standing instructions, the memory that carries across
sessions, the review battery, and the hooks that catch mistakes mechanically
instead of relying on anyone remembering. That's the stuff in here.

## What's in the `.md` files, and why

`CLAUDE.md` is the global instruction file Claude Code loads for every project.
Mine isn't a pile of "be helpful" platitudes — it's a set of corrections for
specific, recurring failure modes. The load-bearing parts:

- **Don't anchor dev-time estimates on human timelines.** Models are trained
  mostly on humans estimating their own dev work, so they inherit a systematic
  *over*-estimate. Left uncorrected, that bias makes the model recommend
  deferring or shrinking work it could just ship — and worse, miss trades where
  30 minutes of upfront refactor saves 20 hours of compute. So: apply the
  correction *before* quoting, and track estimate-vs-actual so the calibration is
  real, not vibes.
- **Evidence tiers for load-bearing claims.** Before relaying anything you'll act
  on, tag the source: `[ran: …]` (saw it execute) / `[read: file:line]` / `[recalled: …]`.
  Recalled is the weakest tier; for anything that matters, run the cheap check
  first. Collapsing these tiers is how confident-but-wrong happens.
- **A review gate for high-blast-radius decisions.** Before locking in anything
  downstream will treat as authoritative — an architecture decision, a public
  message, an irreversible schema change — offer to run the review battery first.
  The trigger is blast radius, not effort.
- **Direct communication, Strunk & White density.** Push back on bad ideas, omit
  needless words, active voice, concrete language. Stated as rules because the
  default drifts toward hedging and filler.
- **The 3-strike rule.** If three fixes haven't resolved it, the model of the
  problem is wrong — stop and reassess instead of flailing a fourth time.

`rules/quality.md` and `rules/testing.md` go deeper on two of these: a
quality framework (calibration, falsifiability, verification tier) and testing
discipline (TDD, mock only the boundaries, colocate tests). Those two are
general doctrine — use them as-is, adapting any examples to your own work.

Read `CLAUDE.md` itself; it's annotated. The placeholder convention is at the top.

## How the pieces fit

- **`CLAUDE.md` + `rules/`** — the standing doctrine, loaded every session.
- **The memory system** — cross-session continuity. An always-loaded index points
  to typed memory files (who you are, how you like to work, project state,
  external pointers). Three skills operate it: `/kickoff` orients at the start,
  `/wrap` writes the deltas at the end, `/retro` does periodic maintenance. Full
  writeup in [`docs/memory-system.md`](docs/memory-system.md). This is the single
  highest-leverage component — it's what makes session N+1 start warm.
- **Skills** (`skills/`):
  - **NineAngel (`/angel`)** — a multi-persona code-review battery (17 calibrated
    reviewer personas + an integrator), vendored from its own repo. The headline.
    Canonical, maintained copy: https://github.com/PropterMalone/NineAngel
  - **Session trio** — `/kickoff`, `/wrap`, `/retro`.
  - **Workflow core** — `/code` (delegate a coding task to a subagent to keep the
    main context clean), `/chain` (run a sequence of audits, each in a fresh
    subagent), `/status` (one-shot view of live background work), `/style`.
  - **Integration stubs** — `/gmail`, `/push`, `/todoist-cli`, `/dashboard`,
    `/docket`. These wire to outside tools you supply; they ship as working
    examples of the pattern, not turnkey features. See
    [`docs/integrations.md`](docs/integrations.md).
- **Hooks** (`hooks/`) — the automation layer that doesn't rely on memory:
  - `post-edit-secret-scan.py` — scans every edit for leaked keys.
  - `post-edit-stub-check.py` — flags TODO/FIXME/unimplemented left behind.
  - `pre-web-rfip.py` — a prompt-injection defense before web fetches.
  - `sanitize-permission-allowlist.py`, `auto-kickoff.sh`, session telemetry, and
    optional infra hooks (serve-to-workstation, email guards) that degrade
    gracefully if you don't use them.
- **`settings.example.json`** — wires the hooks + statusline and ships a sane
  permission posture: file edits auto-accept, but force-push / `reset --hard` /
  `restore` are denied and `rm -rf` / `git push` ask first. (My own config allows
  all Bash and leans on those rails; the shipped default is more conservative —
  widen it once you trust it.)

## Install

```bash
git clone https://github.com/PropterMalone/PropterMaltwo.git
cd PropterMaltwo
./install.sh          # see what it would do, then:
./install.sh --apply
```

`install.sh` copies the machinery into `~/.claude/`, backing up anything it would
overwrite. It **never** clobbers your existing `settings.json` — it drops
`settings.example.json` next to it and tells you what to merge. Re-running is
safe. See `./install.sh --help`.

Then make it yours: open `CLAUDE.md` and replace the `<placeholders>`, wire any
integrations you want ([`docs/integrations.md`](docs/integrations.md)), and start
a session with `/kickoff`.

## Honest caveat on portability

I genuinely don't know how much of this transfers. The people I've handed it to
get *some* use out of it, but I can't tell whether they get as much as I do, more,
or less. A lot of it is shaped to one person's brain and one person's failure
modes — the dev-time correction matters because *I* kept deferring shippable work;
your biases are different. Take it as a worked example to strip for parts, not a
framework to adopt whole. The parts I'd bet travel best: the memory system, the
evidence-tier rule, and NineAngel. The rest, your mileage will vary.

## License

MIT. NineAngel under `skills/angel/` carries its own MIT license (same terms).
