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
    <notify>       an example alert channel (ntfy/Slack/email) — swap or delete
-->

Retro procedure. Run every ~4 days. Covers safety, memory hygiene, and pattern extraction.

## Order of operations (READ FIRST — overrides section numbering)

The memory-MAINTENANCE actions are the main point of retro. Run them FIRST, before any diagnostic checks, so they never get dropped when a session is long or interrupted. Execute the numbered sections in THIS order:

1. **§2 Memory maintenance** — the actions: **calibration archive** (keep ~10 recent in `calibration.md`, compress the rest into `calibration-archive.md`), **lessons absorption** (archive internalized lessons; promote pattern-shaped ones to `patterns.md`), **MEMORY.md topic-index prune**, wrap-coverage audit, per-project staleness. ACTUALLY EDIT THE FILES — don't just report on them.
2. **§3 Pattern extraction.**
3. Then the diagnostic CHECKS last: **§1 Safety review**, **§4 Quality framework**, **§4.5 Dev-task estimate calibration**.
4. **§5 Update dates** — GATED. Do NOT bump `Last retro` / `Next due` / `Last verified` unless the §2 maintenance actions actually completed this run. If you ran out of budget and skipped them, say so explicitly and LEAVE THE DATES STALE so the next session re-triggers. A cosmetic date bump over skipped maintenance is worse than no retro — it makes the gap invisible.
5. **§6 Report.**

Why this order: a checks-first retro tends to run the cheap scans + bump the date but skip the calibration archive and lessons absorption — the substantive work. Front-loading the actions prevents that.

## 1. Safety review

Check each of these and report findings. (These are EXAMPLES for a Linux dev box
running Node/Docker services — keep the ones that match your stack, drop the rest.)

- **Hook harness smoke test**: If you run Claude Code hooks, run their test harness. This catches silent-failure regressions like a path-divergence bug between two hooks that drops per-session deltas.
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

### MEMORY.md topic-index prune

MEMORY.md is loaded at every session start — every row costs context. Topic rows accumulate forever unless pruned. Without an explicit step here, the index grows wooly and the cheap-to-add row becomes the expensive-to-load row.

**Procedure**:

1. Find every file path referenced from MEMORY.md's Topic Index section, and check its last modification date:
   ```bash
   MEMDIR="<memory-dir>"   # adapt: your central memory dir
   awk '/^## Topic Index/,/^## Memory Layout/' "$MEMDIR/MEMORY.md" \
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
   awk '/^## Topic Index/,/^## Memory Layout/' "$MEMDIR/MEMORY.md" \
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
   awk '/^## Topic Index/,/^## Memory Layout/' "$MEMDIR/MEMORY.md" \
     | grep -oE '\(([^)]+\.md)\)' \
     | sed -E 's/[()]//g' \
     | sed -E 's/^([a-z]+[-_][a-z]+[-_][a-z]+)[-_].*\.md$/\1/' \
     | sort | uniq -c | sort -rn \
     | awk '$1 >= 3'
   ```
   A three-token prefix is stricter than two-token (avoids false positives where the third token disambiguates unrelated memories in the same domain). For each ≥3-row cluster: read the row titles, verify they're actually about the same topic before proposing a merge. If they are, propose a merged-file name and present it. If the cluster is unrelated despite the prefix match, skip.

   Don't auto-merge — both checks present candidates and wait for the user's per-cluster decision.

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

## 3. Pattern extraction

- Review session notes since the last retro
- Look for recurring mistakes or insights that should become patterns
- Update `patterns.md` if warranted (merge related patterns, retire obsolete ones)

## 4. Quality framework health (calibration audit)

Executes the meta-falsification audit prescribed by `rules/quality.md` (the global framework) and any per-project extensions (a project may ship its own `QUALITY.md` with a "Calibration logs and scoring loop" + "Meta-falsification" section). Runs against every project that ships calibration logs — the discipline travels with the framework, not with any one project.

### 4a. Discover

```bash
ls ~/Projects/*/calibration.md ~/Projects/*/**/calibration.md 2>/dev/null | sort -u
```

Skip symlinks pointing at templates and any file inside an obvious scaffold dir (`templates/`, `examples/`, `_archive/`).

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

After completing the retro:
- Update `Last retro:` and `Next due:` in CLAUDE.md's Session Management section
- Update `Last verified:` in MEMORY.md to today's date — this field claims the index has been reviewed; if the retro ran, it has been reviewed (the per-project memory staleness audit in §2 IS that review). Don't make it conditional. A stale `Last verified` value is worse than no value because it lies.

(Gated — per the Order of Operations, only bump these if §2 maintenance actually completed.)

## 6. Report

Summarize:
- Safety: clean / issues found (list them)
- Memory: what was archived, promoted, or flagged as stale
- Patterns: any new or updated patterns
- Next retro due: YYYY-MM-DD

Optionally ping an alert channel (`<notify>` — e.g. ntfy/Slack/email) on any safety blocker found, so it surfaces even if you're not at the terminal.
