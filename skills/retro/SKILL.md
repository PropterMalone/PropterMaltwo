---
name: retro
description: Periodic retro — safety review, memory maintenance, pattern extraction
---

<!--
  GENERICIZED skill. The value is the periodic discipline: maintain memory FIRST
  (so it never gets dropped), extract patterns, then run safety + quality
  diagnostics, and only bump the dates if the maintenance actually ran. Safety
  checks and audit scripts are EXAMPLES — adapt to your stack or delete what
  doesn't apply.

  Placeholders:
    <memory-dir>   your central memory dir (Claude Code derives a per-project one
                   from the cwd). See docs/memory-system.md.
    <hooks-dir>    where your Claude Code hook scripts live (if any)
    <scripts>      where your helper scripts live (if any)
    <state-dir>    where your Claude Code harness keeps runtime state (sentinels,
                   status files) — e.g. ~/.claude/state
    <notify>       an example alert channel (ntfy/Slack/email) — swap or delete
-->

Retro procedure. Run every ~4 days. Covers safety, memory hygiene, and pattern extraction.

## Order of operations (READ FIRST — overrides section numbering)

The memory-MAINTENANCE actions are the main point of retro. Run them FIRST, before any diagnostic checks, so they never get dropped when a session is long or interrupted. Execute the numbered sections in THIS order:

1. **§2 Memory maintenance** — the actions: **calibration archive** (keep ~10 recent in `calibration.md`, compress the rest into `calibration-archive.md`), **lessons absorption** (archive internalized lessons; promote pattern-shaped ones to `patterns.md`), **MEMORY.md topic-index prune**, wrap-coverage audit, per-project staleness. ACTUALLY EDIT THE FILES — don't just report on them.
1.5. **§2.7 Follow-up queue** — drain your personal "flag it for later" queue (see §2.7 — an example integration with a task-list API; adapt or delete if you don't keep one).
2. **§3 Pattern extraction.**
3. Then the diagnostic CHECKS last: **§1 Safety review**, **§4 Quality framework**, **§4.5 Dev-task estimate calibration**.
4. **§5 Update dates** — GATED. Do NOT bump `Last retro` / `Next due` / `Last verified` unless the §2 maintenance actions actually completed this run. If you ran out of budget and skipped them, say so explicitly and LEAVE THE DATES STALE so the next session re-triggers. A cosmetic date bump over skipped maintenance is worse than no retro — it makes the gap invisible.
5. **§6 Report.**

Why this order: a checks-first retro tends to run the cheap scans + bump the date but skip the calibration archive and lessons absorption — the substantive work. Front-loading the actions prevents that. (This is the kind of failure the §2 fail-loud guards below and the completion sentinel exist to catch mechanically, not just by discipline.)

## 1. Safety review

Check each of these and report findings. (These are EXAMPLES for a Linux dev box
running Node/Docker services — keep the ones that match your stack, drop the rest.)

- **Hook harness smoke test**: If you run Claude Code hooks, run their test harness (ideally one that re-derives and asserts its own expected hook count, rather than hard-coding a number that drifts). This catches silent-failure regressions like a path-divergence bug between two hooks that drops per-session deltas.
  ```bash
  bash <hooks-dir>/test-hooks.sh
  ```
  Non-zero exit means a hook regressed. Surface the failing hook name(s) and treat as a blocker until fixed — a broken hook is silently corrupting state in real sessions, not just the test sandbox.
- **Leaked secrets**: Grep recent commits across active projects for `.env` contents, API keys, passwords
  ```bash
  for d in ~/Projects/*/; do echo "=== $(basename $d) ==="; git -C "$d" log --oneline -5 --diff-filter=A -- '*.env' '.env*' 2>/dev/null; done
  ```
- **.env permissions**: Verify `.env` files aren't world-readable. Use `-L` to DEREFERENCE symlinks — if your `.env` files are symlinks to a secrets store (a common pattern), a bare `find -perm` flags the symlink itself (always `lrwxrwxrwx`), a false positive. `-L` checks the real target's perms.
  ```bash
  find -L ~/Projects -name '.env' -perm /o+r 2>/dev/null
  ```
- **New services without firewall rules**: Check for listening ports not covered by your firewall
  ```bash
  sudo ss -tlnp | grep -v '127.0.0.1\|::1'
  ```
- **Claude Code version**: Check for updates and apply if behind
  ```bash
  echo "installed: $(claude --version)" && echo "latest: $(npm view @anthropic-ai/claude-code version)"
  ```
  If behind, run `sudo npm install -g @anthropic-ai/claude-code@latest`. Note the version jump in the report.
- **Prompt injection surfaces**: Review any new user-facing input paths added in recent sessions (bot commands, form inputs, API endpoints)
- **Service health**: Check for failed systemd units and crashed Docker containers
  ```bash
  systemctl --user list-units --state=failed
  docker ps --filter "status=exited" --format "{{.Names}} exited {{.Status}}"
  ```
- **Disk space**: Flag if `/` or `/home` over 80%
  ```bash
  df -h / /home | tail -2
  ```
- **Dependency vulns**: Quick `npm audit` across active projects
  ```bash
  for d in ~/Projects/*/; do [ -f "$d/package-lock.json" ] && echo "=== $(basename $d) ===" && npm audit --prefix "$d" 2>/dev/null | tail -3; done
  ```
- **Stale processes**: Scan for unexpected listeners (including loopback), kill any orphaned dev servers
  ```bash
  # All listeners — including 127.0.0.1, which can shadow systemd services
  ss -tlnp | grep -v 'sshd\|tailscaled\|syncthing\|systemd-resolve'
  ```
  Cross-reference PIDs against known services (Docker containers, systemd units, active dev work). For loopback ports, verify each PID matches the expected unit. A manual `node index.js` on a service port creates a zombie that shadows the real service — check for duplicate ports. Kill anything unexplained.

## 2. Memory maintenance

### Calibration archive
- Move session notes older than ~10 sessions to `calibration-archive.md`
- When archiving, compress to **grade + one-liner** only
- Synthesize recurring themes into capability-inventory updates

### Lessons absorption
- Read `lessons.md` — any lessons that have been internalized (reflected in `patterns.md` or changed behavior) should be archived
- Lessons that reveal new patterns → promote to `patterns.md` (keep `patterns.md` at ~15 rules max)

### Task-list reconciliation (example — adapt to your task backend)

If you migrated task managers at some point, or just accumulate hand-entered
tasks between retros: sweep all lists via your task API, propose priority
prefixes and list moves for anything unprefixed/misfiled, and revisit whether
the priority-prefix tiering (see the `dashboard` skill) still works for you —
adjust the convention there if not.

### MEMORY.md topic-index prune

MEMORY.md is loaded at every session start — every row costs context. Topic rows accumulate forever unless pruned. Without an explicit step here, the index grows wooly and the cheap-to-add row becomes the expensive-to-load row.

> **Anchor note (post two-tier-memory decision):** if you've split your memory index into
> a hot tier (MEMORY.md: active projects + high-use topics) and a cold tier (e.g.
> `roster.md` + `topics.md` holding the full portfolio/index), the awk ranges below target
> the live hot-tier headers only. They prune ONLY the hot MEMORY.md file. Cold-tier coverage
> is a separate, harder problem (bloat tends to accumulate there once the hot tier is kept
> lean) — do NOT assume a clean hot-tier pass means the cold files were reviewed. If you
> haven't split your memory this way, ignore this note — the ranges below still apply to
> your single MEMORY.md.

**§2 header preflight (run FIRST — abort the whole prune if it fails):** before any
extraction, assert every section header the awk ranges depend on actually exists in the
live files. If any line below prints `MISSING`, STOP and surface it — a renamed/moved
header is the exact root cause of a silent zero-row no-op (the prune "runs," matches
nothing, and reports false-clean). Do NOT proceed to prune over an empty read.
```bash
M="<memory-dir>/MEMORY.md"
for h in '^## Key topics' '^## Memory Layout' '^## Active projects' '^## Vocabulary'; do
  if grep -qE "$h" "$M"; then echo "OK      $h"; else echo "MISSING $h  <-- ABORT §2"; fi
done
# If you run a cold tier, its files must exist too (their internal header contract is
# a separate design decision for you to define):
for f in roster.md topics.md; do
  p="<memory-dir>/$f"
  [ -f "$p" ] && echo "OK      $f" || echo "MISSING $f"
done
```

**Procedure**:

1. Find every file path referenced from MEMORY.md's Key-topics (or Topic Index) section, and check its last modification date:
   ```bash
   MEMDIR="<memory-dir>"   # adapt: your central memory dir
   awk '/^## Key topics/,/^## Memory Layout/' "$MEMDIR/MEMORY.md" \
     | grep -oE '\[[^]]+\]\(([^)]+\.md)\)' \
     | sed -E 's/.*\(([^)]+)\)/\1/' \
     | sort -u \
     | while read f; do
         path="$MEMDIR/$f"
         if [ -f "$path" ]; then
           mtime=$(stat -c %Y "$path")
           age_days=$(( ( $(date +%s) - mtime ) / 86400 ))
           printf "%4d days  %s\n" "$age_days" "$f"
         else
           printf "MISSING   %s\n" "$f"
         fi
       done | sort -rn
   ```

   **Fail-loud check (run after the block above):** the extraction MUST yield ≥1 referenced
   file. Re-count independently and abort on zero rather than reading silence as "clean":
   ```bash
   M="<memory-dir>/MEMORY.md"
   n=$(awk '/^## Key topics/,/^## Memory Layout/' "$M" \
         | grep -oE '\[[^]]+\]\(([^)]+\.md)\)' | sort -u | wc -l)
   [ "$n" -gt 0 ] && echo "OK — $n topic refs extracted" \
     || echo "ANCHOR MISS — scanned nothing, NOT clean. The header range matched 0 rows; a header rename has re-broken §2. ABORT and fix the anchor before reporting the prune clean."
   ```

2. **Flag for prune review** (do not auto-delete):
   - Files not modified in **60+ days** — candidate for archival or fold into a parent topic
   - **MISSING** files referenced by MEMORY.md but absent on disk — broken link, fix or remove the row
   - Any row whose hook text is itself >200 chars — the index is meant to be ~150-char one-liners

3. **Present candidates to the user** as a numbered list with: age, file path, current MEMORY.md row text. The user decides per row: keep / archive / fold into another topic / delete. Do NOT pre-empt the decision — surface the candidates and wait.

4. **Soft target**: keep MEMORY.md under 200 lines (truncation threshold). If the current line count is >180, prune-pressure is high.

5. **Topic Index row text discipline**: each row is `- [Title](file.md) — one-line hook` under ~150 chars. Rows that have grown into paragraphs need to be folded back into the pointed-to file.

6. **Consolidation pass** — two checks, structural-skew first then pairwise-cluster:

   **(a) Structural skew check** — if any single-token prefix dominates >40% of the topic index, the issue isn't pairwise merging, it's index design. Run:
   ```bash
   awk '/^## Key topics/,/^## Memory Layout/' "$MEMDIR/MEMORY.md" \
     | grep -oE '\(([^)]+\.md)\)' \
     | sed -E 's/[()]//g' \
     | sed -E 's/^([a-z]+)[-_].*\.md$/\1/' \
     | sort | uniq -c | sort -rn | head -5
   ```
   If the top prefix exceeds ~40% of rows: surface this as a structural-reorg candidate. Two reasonable shapes:
   - **Digest file**: collapse the dominant prefix into a single index file (e.g. a `feedback-index.md` cataloging all `feedback-*` rules with one-line summaries). MEMORY.md gets one row instead of many.
   - **Lift to a second tier**: keep the dominant-prefix files but move their topic-index rows into a separate section that loads only on certain triggers (e.g. communication tasks load `feedback-*`, code tasks load `ref-*`). Requires harness work.

   **(b) Pairwise cluster check** — only for semantically-related rows (not just prefix-matched). Run:
   ```bash
   awk '/^## Key topics/,/^## Memory Layout/' "$MEMDIR/MEMORY.md" \
     | grep -oE '\(([^)]+\.md)\)' \
     | sed -E 's/[()]//g' \
     | sed -E 's/^([a-z]+[-_][a-z]+[-_][a-z]+)[-_].*\.md$/\1/' \
     | sort | uniq -c | sort -rn \
     | awk '$1 >= 3'
   ```
   A three-token prefix is stricter than two-token (avoids false positives where the third token disambiguates unrelated memories in the same domain). For each ≥3-row cluster: read the row titles, verify they're actually about the same topic before proposing a merge. If they are, propose a merged-file name and present it. If the cluster is unrelated despite the prefix match, skip.

   Don't auto-merge — both checks present candidates and wait for the user's per-cluster decision.

### Project Index row prune

The topic-index prune above does NOT cover the **Active-projects** table (the
`## Active projects (in-flight)` rows) — and that table is often where MEMORY.md bloat
actually accumulates, because every project's status, intent, and latest-delta tend to
get appended to its row instead of folded into the project's own memory dir. A single
project row hitting 800–1300 chars is common and is a real driver pushing MEMORY.md over
its load limit. Each project has a per-project memory dir that exists precisely to hold
this detail — the Project Index row should be a one-line pointer, not the record itself.

**Procedure**:

1. Measure the table and flag oversized rows:
   ```bash
   awk '/^## Active projects/,/^## Vocabulary/' "$MEMDIR/MEMORY.md" \
     | awk -F'|' 'NF>3 && length($0)>300 {print length($0)"\t"$2}' \
     | sort -rn
   echo "--- Active-projects bytes / total bytes ---"
   awk '/^## Active projects/,/^## Vocabulary/' "$MEMDIR/MEMORY.md" | wc -c
   wc -c "$MEMDIR/MEMORY.md"
   ```

   **Fail-loud check:** the `## Active projects` range MUST match >0 lines (the table is
   never empty while any project is in-flight). Zero lines = header rename, not "no bloat":
   ```bash
   M="$MEMDIR/MEMORY.md"
   n=$(awk '/^## Active projects/,/^## Vocabulary/' "$M" | wc -l)
   [ "$n" -gt 0 ] && echo "OK — Active-projects range = $n lines" \
     || echo "ANCHOR MISS — '## Active projects' matched 0 rows; ABORT, the project-index prune is reading nothing."
   ```
   Note: 0 *oversized* rows (the length>300 filter) is a legitimate clean result once the
   hot tier is kept lean — that can be a signal that bloat now lives in a cold-tier file
   instead, not a miss. The guard above checks the RANGE matched, not that rows were
   over-length.

2. **Flag for prune review** (do not auto-edit): every row over ~300 chars. The target row
   shape is `| Project | Deploy | one-line status + intent + pointer to per-project memory |`
   under ~250 chars.

3. **For each flagged row, the fix is FOLD-DOWN, not deletion:** move the row's accumulated
   detail (status history, decision notes, latest deltas) into the project's per-project memory
   dir — append to or create a file there — then shorten the MEMORY.md row to a one-liner that
   ends with a pointer (e.g. "See per-project memory."). Verify the per-project dir exists;
   create the file if absent. No project loses information — it moves to where it loads on
   demand instead of every session.

4. **Present candidates to the user** as a numbered list (length, project, current row text,
   proposed shortened row + where the detail will land) and wait for per-row approval before
   editing. Same don't-pre-empt rule as the Topic Index prune.

### Handoff prune + dangling-ref cleanup

If you run automated handoff pruning (e.g. a daily cron script that deletes handoffs
older than a threshold, always keeping the newest per dir as a dormant-project
breadcrumb, and writes a report of what it pruned), retro's job is the judgment half:

1. Read the report. If it flags dangling references, fix each listed MEMORY.md line: de-link the dead ref and annotate — `[text](handoff_X.md)` → `text (handoff pruned)`, dropping the `.md` suffix so the scanner stops matching. Never delete whole lines; the row's summary text usually still earns its place (prune it on its own merits via the topic-index step, not because its link died).
2. If the report's timestamp is stale (multiple days old), the cron is dead — check the pruning log and crontab.
3. If handoffs are NOT tracked in version control, plan recovery from a backup, not git, for a wrongly-pruned file.

### Session wrap coverage audit

Sessions that ended without `/wrap` lose calibration grades, lessons, and project deltas — the kind of drift retros exist to catch. If you run a cron-driven back-fill (the `wrap-stale` skill via a runner script), it handles most of this, but mtime drift, timeouts, and oversized transcripts produce gaps. An audit script can identify and bucket uncovered sessions; the retro decides what to act on.

```bash
# adapt: example audit over the last 14 days of transcripts
bash <scripts>/wrap-coverage-audit.sh 14 > /tmp/wrap-coverage.csv
echo "=== bucket counts ==="
tail -n +2 /tmp/wrap-coverage.csv | cut -d, -f1 | sort | uniq -c | sort -rn
```

Example buckets (sessions under ~50 KB filtered out upstream):

- **SIDECAR-WRAPPED** — a `.wrapped` sidecar exists; covered, nothing to do.
- **WRAPPED** — a handoff exists from a live `/wrap`; covered.
- **STALE-WRAPPED** — a handoff exists from the back-fill runner; covered.
- **UNCAUGHT** — no handoff and the runner hasn't processed yet. Let cron catch up; no action unless the count climbs across retros (which would indicate the cron stopped firing — check the runner log for activity).
- **RUNNER-ATTEMPTED-NO-LANDING** — the runner fired but no handoff was produced. This bucket should trend toward zero if your sidecar/dedup logic is working; if it stays non-zero across consecutive retros, investigate up to 3 cases (the runner log captures the `claude -p` stdout). Common causes: `claude -p` exited 0 with a SKIPPED message, an auto-kickoff hook injected context that derailed the agent, an API blip mid-flight.
- **TOO-LARGE** — transcript too big for the back-fill model to absorb; the runner skips by design. Surface one-by-one for a manual decision: hand-wrap in a large-context interactive session via parallel subagents, defer, or accept the loss.

The audit is read-only — it never modifies handoffs or sidecars. Action is per-bucket and per-session; the user decides. Delete this whole sub-step if you don't run a back-fill runner.

### Per-project memory staleness (parallel)

Spawn one Explore subagent per active project (from MEMORY.md's "Active" rows). Launch 3–5 at a time in parallel. Each agent's prompt:

> "Audit the memory dir for project `<project>`. Report under 80 words: (1) files not touched in 2+ weeks, (2) any obviously stale content (status lines contradicted by recent `git -C ~/Projects/<project> log --oneline -20`), (3) missing files that the MEMORY.md index references but don't exist on disk. If all fresh, say 'fresh'."

Collect the reports. Flag anything stale or missing for action this retro.

Fallback if subagents are unavailable — serial diff over your per-project memory dirs:
```bash
# adapt: Claude Code stores per-project memory under dirs keyed off the cwd.
# Point this at wherever yours live and diff against a recent baseline.
for d in <memory-root>/*/memory/; do echo "=== $d ==="; git -C <memory-root-repo> diff --stat HEAD~10 -- "$d" 2>/dev/null || echo "(no git history)"; done
```

### Completion sentinel (write LAST in §2 — gates §5 and serves resume-state)

After the §2 maintenance actions above have ACTUALLY run, write a per-run progress sentinel
recording the real sub-action deltas. §5 refuses to bump any date unless this sentinel
exists and shows non-trivial work — that is the machine-checkable replacement for
self-attestation (which is exactly the mode that fails: a session under time pressure
reports "done" without having actually done the archiving). This same file also serves as
**resume-state**: if a retro is interrupted and re-runs the same day, read the existing
sentinel first to see which sub-actions already completed and skip redoing them.

Fill the counts from what you actually did (use 0 only when a pass genuinely had nothing to
do — an all-zero sentinel does NOT satisfy the §5 gate):
```bash
mkdir -p "<state-dir>"
SENT="<state-dir>/retro-progress-$(date +%F).json"
cat > "$SENT" <<JSON
{
  "date": "$(date +%F)",
  "calibration": {"before": <N>, "after": <M>, "archived": <K>},
  "lessons": {"promoted": <P>, "archived": <A>},
  "topic_index_rows_pruned": <R>,
  "project_index_rows_folded": <F>,
  "wrap_coverage_buckets_reviewed": <true|false>,
  "per_project_staleness_reviewed": <true|false>,
  "notes": "<one line: what was substantive vs. no-op this run>"
}
JSON
echo "wrote sentinel: $SENT"; cat "$SENT"
```
If §2 was skipped or only ran vacuously (e.g. the anchor-miss guards fired), do NOT write a
"complete" sentinel — leave it absent or set the deltas to reflect that nothing substantive
happened, so §5 correctly leaves the dates stale.

## 2.7. Follow-up queue (example integration — adapt or delete)

If you keep a personal "flag it for the agent to look at later" channel — e.g. a
dedicated list in a task-list API that you (not the agent) add items to during the week,
distinct from the agent's own backlog — drain it every retro. The reference setup uses a
Google Tasks list for this:

```bash
gws tasks tasks list --params '{"tasklist":"<your-tasks-list-id>","showCompleted":false}'
```

> `<your-tasks-list-id>` — the list ID for your personal follow-up queue. Resolve it once
> via `gws tasks tasklists list` and hard-code it here (or in a config file) since it's
> stable; a script or query that references it should carry this same comment so a reader
> knows what the ID represents.

Emails may land in this list via a mail client's "add to tasks" feature, carrying a link
back to the source message. For each open item:

1. Read the task title/notes; if a source link is present (e.g. an email link), fetch the
   source message for full context.
2. Investigate proportionally — a quick answer inline in the retro report; anything
   substantial gets delegated or spun into a backlog.md item / project task with a pointer.
3. **Close the loop**: mark the task completed and put the outcome in the task notes first,
   so the answer is visible in the task list:
   ```bash
   gws tasks tasks patch --params '{"tasklist":"<your-tasks-list-id>","task":"<task-id>"}' --json '{"notes":"<one-line outcome + pointer>","status":"completed"}'
   ```
4. Summarize dispositions in the retro report (§6).

Known misfiling mode: a mail client's "add to tasks" feature often drops items into
whichever list the task app's sidebar last had selected — if you know you flagged
something and this list is empty, check your default/inbox list for it (search recent
items with source links) before concluding it's missing.

If an item is urgent, raise it in-session instead — this list is the *non-urgent* channel;
retro cadence is ~4 days.

## 3. Pattern extraction

- Review session notes since the last retro
- Look for recurring mistakes or insights that should become patterns
- Update `patterns.md` if warranted (merge related patterns, retire obsolete ones)

## 4. Quality framework health (calibration audit)

Executes the meta-falsification audit prescribed by `rules/quality.md` (the global framework) and any per-project extensions (a project may ship its own `QUALITY.md` with a "Calibration logs and scoring loop" + "Meta-falsification" section). Runs against every project that ships calibration logs — the discipline travels with the framework, not with any one project.

### 4a. Discover

```bash
find ~/Projects -name calibration.md -not -path '*/templates/*' -not -path '*/_archive/*' | sort -u
```

(Prefer `find` over an `ls`-with-globstar form — the latter depends on a shell
option that's often off by default and can silently find 0 files, no-op'ing the
whole §4 quality audit without telling you.)

Skip symlinks pointing at templates and any file inside an obvious scaffold dir (`templates/`, `examples/`, `_archive/`).

**Fail-loud guard:** the `find` MUST return ≥1 path if you have any projects shipping
calibration logs. If it returns zero and you expected hits, do NOT report "no calibration
files / nothing to audit" silently — abort §4 loudly: "§4a DISCOVERY MISS — scanned
nothing, NOT clean; check the find predicate against the live tree before trusting a clean
§4 report."

### 4b. Parse and bucket-score

For each `calibration.md`:
- Read the table rows (skip the header row and any row whose only content is a placeholder like `_(awaiting first scenario)_` or `_(awaiting first probe result)_`).
- If only the scaffold row remains: report as **"no resolved claims yet"** and move on. Do not invent rates.
- Otherwise count rows where the outcome column is `confirmed` / `refuted` / `partial` / `unresolvable`.
- Compute observed hit-rate per confidence band: 0.5–0.7, 0.7–0.9, 0.9+. (`partial` counts as 0.5 hit; `unresolvable` is excluded from the denominator.)

### 4c. Apply meta-falsification triggers

- **(a) Calibration drift** — for each project with ≥10 resolved claims in a band, flag the 0.7–0.9 band if the observed rate is `< 0.6` or `> 0.95`. If no project has ≥10 resolved claims yet, report **"insufficient data (need ≥10 resolved claims; current: N)"**. Until resolutions accrue, this is the expected state.
- **(b) Falsifier vacuity** — gather all `claims.json` files under projects with calibration logs (`find ~/Projects -name claims.json -path '*/takes/*'`). Sample 10 random `could_be_wrong_if` entries across them. Read each from a hostile-reader stance and judge whether it names: (1) a signal to observe, (2) a procedure to check it, (3) a threshold where applicable. Count failures. Flag if `>30%` (i.e., ≥4/10) fail. The retro-running assistant performs this judgment itself — do not skip it just because it's subjective; that's the point of the audit.
- **(c) Scope abuse** — read each take's headline (the first H1 in `take.md`) and its `scope` field (in `claims.json` or take frontmatter). Ask: does the headline mislead a reader who only sees the headline, given the actual scope? Flag if `>20%` of takes do. With <5 takes total, report the count and your judgment without the percentage gate.
- **(d) Friction kill** — count load-bearing artifacts shipped this calendar month (commits adding/modifying files in `takes/`, `drivers/`, `probes/`, `methodology/`, `docs/`, decision-record files — see your QUALITY.md's "what load-bearing means here"). For each, check whether the changed content includes the discipline (confidence + could_be_wrong_if + evidence on claims; calibration-log entry where applicable). Flag if the discipline was skipped on `>2` artifacts in the month.

### 4d. Report

Emit as a section in the retro report. Structure:

```
## Quality framework health

**Calibration files discovered**: N (M with resolved claims, K scaffold-only)

### Per-project audit
- <project-path>: <resolved-count> resolved claims (<bucket breakdown or "scaffold only">)
- ...

### Meta-falsification trigger checks
- (a) Calibration drift: <result or "insufficient data (need ≥10 resolved claims; current: 0)">
- (b) Falsifier vacuity: <X/10 entries fail shape rule — UNDER/OVER threshold>
- (c) Scope abuse: <count + flag status>
- (d) Friction kill: <count + flag status>

### Action items
<any flagged triggers convert to action items here; if nothing flags, write "none">
```

(Skip this whole section if your projects don't ship calibration logs / `claims.json` takes — it's the heavyweight tier of the quality framework.)

## 4.5. Dev-task estimate calibration

Scan your dev-estimates log (`<memory-dir>/dev_estimates.md`) for entries logged since the previous retro. The log captures dev-task duration estimates quoted in chat (load-bearing for ship-vs-defer decisions) versus the actual time the work took.

Per CLAUDE.md, model training data anchors on human-developer pacing, so the model systematically overestimates. The log is the recalibration mechanism.

### Read

```bash
cat <memory-dir>/dev_estimates.md
```

### Compute

For each complexity bucket (`tweak`, `single-file edit`, `new module + tests`, `cross-module refactor`, `architecture change`):
- Median of `(actual / estimate)` ratios over entries in this period
- Count of entries in the bucket

### Trigger for action

- If the median ratio in any bucket is `< 0.5` (i.e., consistently 2×+ over): the bucket's calibration target in CLAUDE.md / `dev_estimates.md` is too high. Recommend tightening the target.
- If the median ratio is `> 1.5` for any bucket: UNDERestimating in that bucket — the under-bias surfaced; flag it (rare but possible if scope creep is systematically excluded from initial estimates).
- If a bucket has zero entries: note "no data this period" — not a problem unless it's been multiple retros without data.

### Report

Add a section to the retro report:

```
## Dev-task estimate calibration

**Entries since last retro**: N

| Bucket | Count | Median actual/estimate | Flag |
|--------|-------|------------------------|------|
| tweak | <n> | <ratio> | <ok / over / under> |
| single-file edit | ... | | |
| ... | | | |

### Recalibration recommendations
<bullet list of bucket-specific target adjustments, or "none">
```

Do not edit `dev_estimates.md` from this audit — it's the data source. Only update CLAUDE.md's bucket-target table if action items warrant.

## 5. Update dates

**ALL THREE date fields are GATED by the Order-of-operations section above — none of them
bump unless §2 maintenance actually completed this run.** That gate is authoritative; this
section is subordinate to it. The machine-checkable gate is today's progress sentinel
(written by §2, see "Completion sentinel" above): if it is absent or shows no real work,
LEAVE ALL DATES STALE so a stale-runner (if you have one) re-fires.

Read the sentinel first:
```bash
SENT="<state-dir>/retro-progress-$(date +%F).json"
if [ -s "$SENT" ]; then echo "=== today's sentinel ==="; cat "$SENT"; else echo "NO SENTINEL FOR TODAY — §2 did not record real work. DO NOT bump any date."; fi
```
Bump dates ONLY if the sentinel exists AND shows non-trivial deltas (e.g. calibration
archived, lessons promoted/archived, or rows actually pruned — not an all-zero sentinel
from a vacuous pass over an empty read). Then:
- Update `Last retro:` and `Next due:` in CLAUDE.md's Session Management section.
- Update `Last verified:` in MEMORY.md to today's date. This field claims the index was
  reviewed; the §2 maintenance + per-project staleness audit IS that review. **Don't
  make this bump conditional on anything beyond the gate above** — once §2 genuinely
  ran, don't withhold the bump for cosmetic reasons. It does NOT override the gate,
  though: a fresh `Last verified` date suppresses any stale-runner's re-fire, so bumping
  it over skipped/vacuous maintenance hides the gap. A stale value that correctly signals
  "re-run me" is better than a fresh value that lies.

## 6. Report

Summarize:
- Safety: clean / issues found (list them)
- Memory: what was archived, promoted, or flagged as stale
- Patterns: any new or updated patterns
- Next retro due: YYYY-MM-DD

Optionally ping an alert channel (`<notify>` — e.g. ntfy/Slack/email) on any safety blocker found, so it surfaces even if you're not at the terminal.
