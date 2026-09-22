# Integrations (the seams)

Some skills wire Claude Code to outside tools: email, a task manager, a browser
on another machine. These ship as **stubs**: real, working examples of the
*pattern*, but they depend on tooling and credentials only you can supply. Each
stub's `SKILL.md` opens with an `INTEGRATION STUB` banner naming its dependency.
This file is the index of seams and how to plug into them.

The point of shipping them at all: they're meaningful parts of how the workflow
actually runs. Seeing the real shape, even one you can't run as-is, beats a
vague "you could integrate email here."

## The skills and what each needs

| Skill | External dependency | What it does |
|-------|---------------------|--------------|
| `gmail` | A Gmail/Google Workspace CLI + your Google account. The reference setup uses a `gws`-style CLI wrapped by a local `~/bin/<your-email-cli>` script. | Create email **drafts** (never auto-send), with a mandatory sanitizer and a clobber-guard that refuses to overwrite a draft you hand-edited. |
| `push` | An SSH-reachable workstation with a browser + a small `serve-to-workstation.sh`. | Serve a local file (HTML/PDF/image) over HTTP through an SSH tunnel so you can view it in your workstation's browser. |
| `dashboard` | Google Tasks (via the `gws` CLI) + a local `backlog.md`. | Merge your task manager and a local backlog into one prioritized view. Formerly Todoist-backed; the backend swap was a one-skill edit. |
| `docket` | A planner CLI + a queue tool + calendar access. | A time-aware daily plan that coordinates your day with the agent's background work. |

`docket` and parts of `dashboard`/`status` lean on external planner and queue
tools that are **not** in this repo. Treat those skills as blueprints: the
choreography is real, the specific CLI calls are placeholders. Swap your own
tools in or delete the steps.

## Wiring pattern: the email draft seam (worked example)

The most load-bearing seam, because it touches the "never send, only draft" safety
rule (see CLAUDE.md → Outbound Messages):

1. Install a Google Workspace CLI (a `gws`-style tool) and authenticate it.
2. Write a thin wrapper script (the reference calls it `~/bin/gmail`) that:
   - builds the message as **`multipart/alternative`** (a `text/plain` part plus a
     `text/html` part), one long line per paragraph, with any command, path, or URL
     on a line of its own. Never pre-wrap prose by hand. Bare plain text and
     generated plain-text fallbacks may wrap and split commands, while the tested
     rich-text path preserves line structure. Keep a `--plain` flag for lists that
     require single-part plain text. `format=flowed` is unsafe for anything you'll
     open in a compose window.
   - runs a **sanitizer** before any create/send;
   - records what it wrote so a later delete/update can detect that you edited
     the draft in the web UI and **refuse** to clobber it.
3. Point the `gmail` skill at your wrapper (`<your-email-cli>`).
4. The `block-gmail-ack-warnings.py` and `block-raw-draft-delete.py` hooks enforce
   the guards mechanically; they only fire on matching commands, so they're
   harmless if you don't use this integration.

Multi-account? Switch with an env var pointing at a per-account config dir, e.g.
`GOOGLE_WORKSPACE_CLI_CONFIG_DIR=~/.config/gws-<account>`.

## Wiring pattern: notification and task-tracker hook points

The unattended scripts in `scripts/` never hardcode a notifier or a task manager.
Each one takes a command you supply, and treats a missing or broken hook as a
skip rather than a failure — a sweep that fails because your notifier moved is a
sweep you stop trusting.

| Script | Env var | Called with | When |
|--------|---------|-------------|------|
| `adr-sweep.py` | `ADR_SWEEP_NOTIFY` | `(title, body)` | Once per run, only if something new fired |
| `adr-sweep.py` | `ADR_SWEEP_TASK` | `(title, notes)` | Once per **new** fire or hard support loss |
| `monthly-lint-dead-sweep.sh` | `NOTIFY_CMD` | `(title, body)` | Only when a project fails the dead-code gate |

Anything that takes two positional arguments works: a one-line `curl` to a push
service, a `mail` invocation, a CLI that adds to your task manager. Write it once
as a small script on `PATH` and point all three at it — one place owns the
channel, and you can silence everything by moving one file.

`scripts/adr-sweep.py` documents its full configuration surface (root dirs, log
path, memory root, decisions subdir) in its module docstring; see
[`decision-records.md`](decision-records.md) for what it's doing and why.

## Secrets: keep them out of the repo and out of the model's context

Two scripts in `scripts/` encode the hygiene:

- **`scrub-secrets`** — reads a `KEY=value` secrets file and scans your project
  dirs for any hardcoded secret *values*, reporting filenames only (never echoing
  the value). Run it after rotating a credential to confirm nothing leaked into
  tracked files. It can optionally redact in place with `<REDACTED:KEY>` markers.
- **`secret-from-drop`** — moves a secret from a temp "drop" location into a
  target secrets file and wipes both copies, without ever printing the value.
  Useful when you have to get a credential from another machine without it
  landing in shell history or the session transcript.

Recommended layout (the reference setup's default):

- Per-project `.envrc` (committed) that loads secrets via `direnv`.
- Actual secret values in `~/.local/share/secrets/<name>.env`, **outside** any
  repo, never tracked.
- `.env` files are git-ignored; only `.env.example` is committed.

The rule behind all of it: a credential should never enter a file the model
reads, a repo you push, or your shell history.

## Cross-model review (`/angel --cross`)

The `--cross` flag on the NineAngel review battery runs a **second opinion on a
different model than Claude**, the one model-independence axis a same-model
persona battery (all personas, all multiball passes, are Claude) structurally
can't cover. It shells out to an external model CLI over the same diff, gates the
findings (a verbatim code-quote must match the diff, plus a 0.6-confidence floor),
and appends them as **advisory**. It never re-ranks or auto-merges into Claude's
own Top 5.

What you must supply (same bring-your-own pattern as the email seam above):

- **A second-opinion model CLI on `PATH`.** The vendored
  `skills/angel/scripts/xreview.py` defaults to the **`gemini`** CLI (Google's
  Gemini CLI) and accepts `--backend codex` for the **OpenAI Codex** CLI. Install
  and authenticate whichever you use. Without one, `--cross` fails with a clear
  message and the main review proceeds unaffected; the cross leg must never block
  or fail the report.

Safety seam: `xreview.py` refuses to run under any path listed in the
`XREVIEW_GUARD_PATHS` env var (colon-separated). Point it at directories holding
code a third-party model must never see. Default empty (no guard).

The same cross-model pass is baked into the **anonymization gate** too
(`/angel pii deanon`, the De-Anon step): a different model re-checks the
de-anonymization, because model-independence catches re-identification the
same-model pass rationalizes away.
