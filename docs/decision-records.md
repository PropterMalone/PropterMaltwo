# Decision records: the whole lifecycle

Most ADR conventions cover one moment — the day a decision gets written down.
That's the cheap moment. A decision is also alive when someone touches the code
it governs, and when the world it assumed changes. Neither of those moments
reads a file nobody opens.

This is the lifecycle that gives a decision corpus a **read side**: a template
that forces a runnable falsifier, a mechanical sweep that runs them, and a human
step that adjudicates what the sweep found. Write → sweep → adjudicate → drain.

The pieces:

| Piece | Where | Does |
|-------|-------|------|
| Template | `templates/adr-template.md` | The frontmatter fields and the two authoring runs |
| Per-project ADRs | `<project>/docs/decisions/NN-slug.md` | Decisions binding one codebase |
| House ADRs | `~/.claude/docs/decisions/NN-slug.md` | Decisions binding *every* project, cited `house:NN` |
| Sweep | `scripts/adr-sweep.py` + `scripts/adr-falsifier-sweep.sh` | Runs every falsifier weekly, writes verdicts into the ADR files |
| Adjudication | `/retro` → the decision-record step in [`skills/retro/SKILL.md`](../skills/retro/SKILL.md) | Decides whether each fire was real, drains drafts, backfills old ADRs |

## 1. Two tiers: project and house

A project ADR lives in that project's `docs/decisions/` and binds that codebase.
That's the normal case and the default.

Some decisions keep getting re-made. A deployment rule earned by one service's
outage gets re-derived from scratch by the next service. A data-capture
convention gets re-argued in a second project and lands slightly different. The
corpus *re-learns* instead of compounding, because each project's decisions dir
is a silo.

So a decision that recurs across projects gets promoted to **one house ADR** in
the shared config dir, cited from project ADRs and hook messages as `house:NN`.
Promotion is opportunistic, not a project: when you catch yourself deciding
something a second project already decided, write the house ADR then, and have
both project ADRs cite it.

**Citation grammar** (the sweep resolves all of these):

- `house:NN` — the shared cross-project tier
- `angel:NN` — the review-battery skill's own decisions
- `<project>:NN` — another project's dir
- `NN` — bare, **only** inside the same decisions dir, because every dir numbers
  independently from `01`
- `mem:<slug>` / `mem:<project>/<slug>` — a memory file (see
  [`memory-system.md`](memory-system.md))

The house tier is *not* a place to put doctrine that belongs in `CLAUDE.md`.
CLAUDE.md is loaded into every session whether relevant or not, so it holds
assistant-behavior rules and stays as small as it can. Project-architecture
doctrine goes to a house ADR, which loads only when someone cites or sweeps it,
and which gets the lifecycle below. If you're deciding where a rule goes: does it
change how the assistant behaves (CLAUDE.md) or how software gets built (house
ADR)?

## 2. `falsifier_cmd`: the field that makes the read side possible

The template's `falsifier_cmd:` frontmatter holds `{label, cmd}` entries. Each
`cmd` **decides its own verdict**:

```
exit 0   clean   — the condition the ADR bets against was NOT observed
exit 1   fired   — it WAS observed
anything else    — the command broke. Never read as a fire.
stdout           — the observation, recorded verbatim (first non-empty line)
```

That exit contract is the whole interface, and two of its properties are load-
bearing:

**The threshold lives inside the command.** A cmd that prints a number and exits
0 regardless is not a falsifier — nothing downstream can act on it without a
human reading the number, which is exactly the reader you don't have. This is a
mistake that is very easy to make; the ADR that first specified this sweep
shipped three falsifiers that printed counts with no threshold, and so could not
have been applied by the sweep it was specifying.

**Breakage is never a fire.** A falsifier that fires when its own `grep` path
moves trains you to ignore fires, which is worse than having no read side at all.
The sweep classifies every non-0/1 exit — timeouts included — as an error, and a
run with any errored label won't self-heal an existing line either.

The template also requires two runs on the day the ADR ships, recorded in
**Evaluated by** and **Status quo check**:

- **Forward**, proving the falsifier is computable at all from instruments that
  exist. An ADR whose falsifier can't be computed is unfalsifiable in practice no
  matter how concretely it's worded.
- **Backward against existing data**, proving the threshold *discriminates*. A
  forward run says "not yet met" for a well-posed and an ill-posed threshold
  alike. If the status quo already passes, the falsifier is decorative — it will
  read as a pass no matter what the change did.

That requirement came out of an audit: of the pre-registered triggers that had
fired and gone unadjudicated, several couldn't be settled *even by someone who
wanted to*. Not "nobody decided" — "the rule as written cannot be applied to the
data that exists."

## 3. The weekly mechanical sweep

`adr-falsifier-sweep.sh` is a cron entry point: `flock` for single-instance, an
absolute interpreter because cron's PATH isn't a login shell's, and nothing else.
All logic is in `adr-sweep.py`. **No model is involved** — that's the point. An
agent re-deriving shell-computable facts every week is the expensive way to learn
nothing new.

Each run walks every decisions dir it's configured to see (house, the vendored
review skill, and every repo under your projects root — all overridable, see the
script's docstring), and for each ADR:

**Pass 1 — falsifiers.** Run each `cmd` from the repo root with `$ADR_FILE` and
`$ADR_DIR` in its environment. A fire writes one line into that ADR's own
frontmatter:

```yaml
fired: '2026-09-14 — sweep-noise: fires=7 false=4'
```

Re-fires overwrite in place. A clean run **removes** an unadjudicated line
(self-heal). An adjudicated line is untouchable.

**Pass 2 — the support cascade.** An ADR declares what it rests on:

```yaml
depends_on:
  - ref: house:02
    claim: the deploy-from-built-dist rule this decision's rollback path assumes
  - ref: mem:patterns
    claim: "#11 — a second source of truth drifts"
```

The sweep resolves every ref and writes into the *dependent* when a ref dies:

```yaml
support_lost: '2026-09-14 — house:02 retracted; mem:patterns missing'
```

Missing, `retracted`, `rejected`, or carrying an adjudicated-real fire are **hard**
losses (they open a tracker item). `superseded` is a **soft** loss recorded as
`superseded→<successor>`, because dependents usually inherit the successor.

**One hop only.** A `support_lost` ADR keeps its own status until a human flips
it, so nothing propagates without adjudication. A transitive cascade turns one
false positive into twenty in a single run.

This is why `retracted` and `superseded` are different statuses, and why any
status leaving `draft`/`active` must set `until:`. Superseded means the world
changed and a successor governs. Retracted means the premise was false and every
dependent needs a fresh look. The file then carries its own validity interval, so
"why did we believe this in August" stays answerable after "is this true now"
flips.

**State lives in the ADR file, not a registry.** A central falsifier registry was
the obvious design and was rejected: a second source of truth drifts. The ADR
carries its own verdict; the append-only log carries the history.

**Sweep writes are never committed.** An unattended committer running across
every repo on the machine risks wrong-branch commits, wrong-identity commits, and
index collisions with live sessions. An uncommitted line that a destructive git
op wipes simply self-heals at the next sweep.

### The log

Every evaluation, fired or clean, appends one TSV line to `$ADR_SWEEP_LOG`:

```
<iso8601>  <alias>:<file>  falsifier|support|lint|error  <label>  <status>  <exit>  <observation>
```

and each run ends with exactly one `run` line:

```
<iso8601>  -  run  -  done  0  adrs=42 cmds=9 fired=0 lost=0 errors=0 new=0
```

That last line is the **liveness heartbeat**. A read side that quietly stopped
running looks identical to one finding nothing, so something outside the sweep
has to check it: `/kickoff` flags it when the newest `run` line is more than ~8
days old. Build that check *outside* the thing it's checking — a watchdog a dead
process is responsible for starting is not a watchdog.

### Optional hook points

A **new** fire (no line there before) can push a notification and open one
tracker item. Both are optional commands you supply — `ADR_SWEEP_NOTIFY` and
`ADR_SWEEP_TASK`, each taking `(title, body)`. Absent or non-executable means
skipped, never an error. Re-fires touch frontmatter and log only, so a standing
problem nags once, not weekly.

## 4. The human half: adjudicate, drain, backfill

The sweep's job is **evaluation**. It doesn't decide what a fire means. That
belongs to `/retro` (see the decision-record step in
[`skills/retro/SKILL.md`](../skills/retro/SKILL.md)), which does three things:

**Adjudicate.** For every `fired:` / `support_lost:` line the sweep wrote, re-run
the command by hand, decide real or false, and append the verdict in place:

```yaml
fired: '2026-09-14 — sweep-noise: fires=7 false=4 — adjudicated: real 2026-09-17'
```

That suffix is the *only* hand edit to a sweep-written line. An
adjudicated-**real** line means the ADR needs revising, superseding, or
retracting, and the sweep re-flags it every week until you do. An
adjudicated-**false** line suppresses re-fires — and is itself a signal: if most
fires come back false, the falsifier is miscalibrated and the read side is
theater.

**Drain the drafts.** New ADRs are born `status: draft`. Promotion to `active`
requires a **fresh-context reader** — a later session, or the review battery —
who checks and adjudicates any fire first. Every retro gives each outstanding
draft one of four outcomes: promote, reject, supersede, or hold-with-a-stated-
reason. A draft that has been held three retros running gets flagged as stalled;
"still thinking about it" three times is a decision not to decide.

**Backfill.** Old ADRs predate the fields. A few per retro (five is a workable
rate) get their prose "Could-be-wrong-if" converted into a real `falsifier_cmd`
under the exit contract, and a `depends_on:` added for what they actually rest
on. Backfill, not the engine, is the bottleneck — writing the sweep is a day;
giving a corpus of ADRs runnable falsifiers is months of small increments. Plan
for the increments.

**One adjacent rule that belongs here**, because it's the same failure in a
different file tree: before deleting or renaming any memory file, grep for
`[[link]]` and `mem:` references to it across every memory and decisions dir, and
retarget each dependent first. `depends_on: mem:<slug>` means a memory file can
now be load-bearing for a decision, and a silent deletion orphans it.

## 5. If you're adopting this from scratch

Start smaller than all of the above:

1. Use `templates/adr-template.md` and actually fill in **Evaluated by** and
   **Status quo check**. If you do nothing else, do this — it's the step that
   turns "could be wrong if circumstances change" into something checkable, and
   it costs one line.
2. Add `falsifier_cmd:` to new ADRs only. Don't backfill first; you'll stall.
3. Wire the weekly cron once you have a handful of falsifiers. Below that, run
   `adr-sweep.py --dry-run` by hand at retro.
4. Add the house tier when you catch the second re-decision, not before. A
   doctrine tier with one entry is a folder.
