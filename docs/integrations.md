# Integrations (the seams)

Some skills wire Claude Code to outside tools — email, a task manager, a browser
on another machine. These ship as **stubs**: real, working examples of the
*pattern*, but they depend on tooling and credentials only you can supply. Each
stub's `SKILL.md` opens with an `INTEGRATION STUB` banner naming its dependency.
This file is the index of seams and how to plug into them.

The point of shipping them at all: they're meaningful parts of how the workflow
actually runs. Seeing the real shape — even one you can't run as-is — beats a
vague "you could integrate email here."

## The skills and what each needs

| Skill | External dependency | What it does |
|-------|---------------------|--------------|
| `gmail` | A Gmail/Google Workspace CLI + your Google account. The reference setup uses a `gws`-style CLI wrapped by a local `~/bin/<your-email-cli>` script. | Create email **drafts** (never auto-send), with a mandatory sanitizer and a clobber-guard that refuses to overwrite a draft you hand-edited. |
| `push` | An SSH-reachable workstation with a browser + a small `serve-to-workstation.sh`. | Serve a local file (HTML/PDF/image) over HTTP through an SSH tunnel so you can view it in your workstation's browser. |
| `todoist-cli` | The Todoist `td` CLI + your Todoist API token. | View/create/complete tasks from the session. |
| `dashboard` | Todoist (via MCP or `td`) + a local `backlog.md`. | Merge your task manager and a local backlog into one prioritized view. |
| `docket` | A planner CLI + a queue tool + calendar access (the reference setup uses bespoke `docket` + `phyllis` CLIs). | A time-aware daily plan that coordinates your day with the agent's background work. |

`docket` and parts of `dashboard`/`status` lean on two bespoke tools that are
**not** in this repo — a queue (`phyllis`) and a planner (`docket`). Treat those
skills as blueprints: the choreography is real, the specific CLI calls are
placeholders. Swap your own tools in or delete the steps.

## Wiring pattern: the email draft seam (worked example)

The most load-bearing seam, because it touches the "never send, only draft" safety
rule (see CLAUDE.md → Outbound Messages):

1. Install a Google Workspace CLI (a `gws`-style tool) and authenticate it.
2. Write a thin wrapper script (the reference calls it `~/bin/gmail`) that:
   - builds the message as `text/plain`, one long line per paragraph (no manual
     wraps — they break copy-paste of URLs/commands);
   - runs a **sanitizer** before any create/send;
   - records what it wrote so a later delete/update can detect that you edited
     the draft in the web UI and **refuse** to clobber it.
3. Point the `gmail` skill at your wrapper (`<your-email-cli>`).
4. The `block-gmail-ack-warnings.py` and `block-raw-draft-delete.py` hooks enforce
   the guards mechanically — they only fire on matching commands, so they're
   harmless if you don't use this integration.

Multi-account? Switch with an env var pointing at a per-account config dir, e.g.
`GOOGLE_WORKSPACE_CLI_CONFIG_DIR=~/.config/gws-<account>`.

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
- Actual secret values in `~/.local/share/secrets/<name>.env` — **outside** any
  repo, never tracked.
- `.env` files are git-ignored; only `.env.example` is committed.

The rule behind all of it: a credential should never enter a file the model
reads, a repo you push, or your shell history.
