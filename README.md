# PropterMaltwo

My actual Claude Code environment, genericized for sharing. If you sat down at
a blank machine, this is what you'd lay down to work the way I work. Drop it
onto `~/.claude`, plug in your own data, and go.

Most of how I've gotten better at using Claude Code this year isn't so much my
personal, human skill improving as it is changes I've made to this environment.

## The basics, if you're new to this

Everything I do is a project, and a project is a folder. Each app, bot,
research question, or one-off pipeline gets its own folder under
`~/Projects/<name>`, and each folder is a git repo. Claude Code keys on this:
`cd` into a folder and it loads that project's `CLAUDE.md` and that project's
memory directory, both tied to the folder path. The global `~/.claude` (what
this repo is a snapshot of) only holds what applies everywhere: doctrine,
skills, hooks, and an index of what projects exist and where they stand. I make
a new folder for basically any new idea. Most of them die, and that's fine.

I run Claude Code on a headless Linux box and sit at a different machine
(`<workstation>`) with the browser. A few hooks and skills only exist because
of that split, like serving a file to the workstation's browser, or running an
OAuth callback through an SSH tunnel. If you work on one machine you can skip
those.

For outside services, I use a plain CLI where a decent one exists, and an MCP
server where the service actually needs interactive auth. CLIs are cheaper in
tokens. More importantly, hooks can inspect a shell command before it runs, so
a CLI is guardable in a way an MCP call isn't. What I actually use:

- Google (Gmail / Calendar / Tasks / Drive): Google's `gws` CLI
  (`npm i -g @googleworkspace/cli`). Separate accounts get separate config dirs
  via `GOOGLE_WORKSPACE_CLI_CONFIG_DIR`, so personal and work tokens never mix.
  The `/dashboard` and `/docket` skills sit on top of this.
- Email: a small wrapper that only writes drafts. Nothing gets sent unless I say
  send it, and two hooks enforce the sharp edges. The draft-first rule is the
  part worth copying whatever mail tool you use.
- GitHub: `gh` plus one SSH host alias per account, with the identity-guard
  hooks (below) checking every push against a per-repo tag.
- Phone: [ntfy](https://ntfy.sh). Any cron job or hook can curl a topic and it
  shows up on my phone.
- Chat platforms and anything OAuth-heavy: MCP servers, configured per-project
  where possible so a bot's credentials don't ride into unrelated sessions.
- The web: the built-in fetch/search tools, behind a hook that reminds the model
  that fetched content is data, not instructions.

Background work is cron. Scheduled jobs run `claude -p` (headless one-shot mode)
for things like wrapping sessions that ended without a handoff. Long-running
services are ordinary systemd units. There's no orchestration framework, just
cron, systemd, and git.

## What's in the `.md` files, and why

`CLAUDE.md` is the global instruction file Claude Code loads for every project.
Mine is mostly a set of corrections for
specific, recurring failure modes.

- **Don't anchor dev-time estimates on human timelines.** Models are trained
  mostly on humans estimating their own dev work, so they inherit a systematic
  *over*-estimate. Left uncorrected, that bias makes the model recommend
  deferring or shrinking work it could just ship, and miss trades where
  30 minutes of upfront refactor saves 20 hours of compute. So: apply the
  correction *before* quoting, and track estimate-vs-actual so the calibration is
  real, not vibes.
- **Evidence tiers for load-bearing claims.** Before relaying anything you'll act
  on, tag the source: `[ran: …]` (saw it execute) / `[read: file:line]` / `[recalled: …]`.
  Recalled is the weakest tier; for anything that matters, run the cheap check
  first. Collapsing these tiers is how confident-but-wrong happens.
- **A review gate for high-blast-radius decisions.** Before locking in anything
  downstream will treat as authoritative (an architecture decision, a public
  message, an irreversible schema change), offer to run the review battery first.
  The trigger is blast radius, not effort.
- **Direct communication, Strunk & White density.** Push back on bad ideas, omit
  needless words, active voice, concrete language. Stated as rules because the
  default drifts toward hedging and filler.
- **The 3-strike rule.** If three fixes haven't resolved it, the model of the
  problem is wrong. Stop and reassess instead of flailing a fourth time.

`rules/quality.md` and `rules/testing.md` go deeper on two of these: a
quality framework (calibration, falsifiability, verification tier) and testing
discipline (TDD, mock only the boundaries, colocate tests). Those two are
general doctrine; use them as-is, adapting any examples to your own work.

Read `CLAUDE.md` itself; it's annotated. The placeholder convention is at the top.

## How the pieces fit

- **`CLAUDE.md` + `rules/`** — the standing doctrine, loaded every session.
- **The memory system** — cross-session continuity. An always-loaded index points
  to typed memory files (who you are, how you like to work, project state,
  external pointers). Three skills operate it: `/kickoff` orients at the start,
  `/wrap` writes the deltas at the end, `/retro` does periodic maintenance. Full
  writeup in [`docs/memory-system.md`](docs/memory-system.md). This is the single
  highest-leverage component: it's what makes session N+1 start warm.
- **Skills** (`skills/`):
  - **NineAngel (`/angel`)** — a multi-persona code-review battery (19 calibrated
    reviewer personas + an integrator), with an optional cross-model second opinion
    (`--cross`) that reviews the same diff on a different model than Claude. Vendored
    from its own repo. The headline.
    Canonical, maintained copy: https://github.com/PropterMalone/NineAngel
  - **Session trio** — `/kickoff`, `/wrap`, `/retro`.
  - **Workflow core** — `/code` (delegate a coding task to a subagent to keep the
    main context clean), `/chain` (run a sequence of audits, each in a fresh
    subagent), `/status` (one-shot view of live background work), `/style`.
  - **Integration stubs** — `/gmail`, `/push`, `/dashboard`, `/docket`. These
    wire to outside tools you supply; they ship as working examples of the
    pattern, not turnkey features. (`/dashboard` now targets Google Tasks;
    the Todoist variant was retired after a task-manager migration, and swapping
    the backend was a one-skill edit, which is the point of the pattern.) See
    [`docs/integrations.md`](docs/integrations.md).
- **Hooks** (`hooks/`) — the automation layer that doesn't rely on memory:
  - **GitHub identity guards** (`gh-identity-guard.py` +
    `gh-commit-author-guard.py`), new since the last share, and the piece I'd
    least want to run without if you publish under a pseudonym. A per-repo
    identity tag (`git config claude.identity <id>`) is validated against a
    single identity map (`github-identity-map.example.json`) before any
    push/repo-create/commit: wrong SSH host alias, wrong gh account, wrong
    author for the tag → deny with a fix-and-retry message. Fail-closed,
    pure-validator (no side effects), accident-prevention threat model.
    Static parsing won't stop a determined adversary, but it reliably
    catches the realistic accident class in testing. Ships with a self-contained
    61-case behavioral suite (`test-gh-identity-hooks.py`). Behavioral tests
    matter for guards, because a guard broken by a stray refactor fails OPEN
    and looks identical to a working one.
  - `angel-multiball-guard.py` — enforces the review-battery floor (single-pass
    reviews get denied when doctrine says N≥2).
  - `post-edit-secret-scan.py` — scans every edit for leaked keys.
  - `post-edit-stub-check.py` — flags TODO/FIXME/unimplemented left behind.
  - `pre-web-rfip.py` — a prompt-injection defense before web fetches.
  - `sanitize-permission-allowlist.py`, `auto-kickoff.sh`, session telemetry, and
    optional infra hooks (serve-to-workstation, email guards) that degrade
    gracefully if you don't use them.
- **`settings.example.json`** — wires the hooks + statusline and ships a sane
  permission posture: file edits auto-accept, but force-push / `reset --hard` /
  `restore` are denied and `rm -rf` / `git push` ask first. (My own config allows
  all Bash and leans on those rails; the shipped default is more conservative.
  Widen it once you trust it.)

## Install

```bash
git clone https://github.com/PropterMalone/PropterMaltwo.git
cd PropterMaltwo
./install.sh          # see what it would do, then:
./install.sh --apply
```

`install.sh` copies the machinery into `~/.claude/`, backing up anything it would
overwrite. It **never** clobbers your existing `settings.json`; it drops
`settings.example.json` next to it and tells you what to merge. Re-running is
safe. See `./install.sh --help`.

Then make it yours: open `CLAUDE.md` and replace the `<placeholders>`, wire any
integrations you want ([`docs/integrations.md`](docs/integrations.md)), and start
a session with `/kickoff`.

## Honest caveat on portability

I genuinely don't know how much of this transfers. The people I've handed it to
get *some* use out of it, but I can't tell whether they get as much as I do, more,
or less. A lot of it is shaped to one person's brain and one person's failure
modes. Take it as a worked example to strip for parts, not a
framework to adopt whole. The parts I'd bet travel best: the memory system, the
evidence-tier rule, and NineAngel. The rest, your mileage will vary.

## License

MIT. NineAngel under `skills/angel/` carries its own MIT license (same terms).
