---
name: push
description: Serve a local file to a workstation browser over an SSH tunnel (integration stub). Renders Markdown first.
---
> **INTEGRATION STUB.** This skill wires Claude Code to an external tool/account that you must supply and configure: **an SSH-reachable workstation with a browser + a small HTTP serve script (serve-to-workstation)**. It ships as a working example of the integration pattern, not a turnkey feature. See `docs/integrations.md` for what to install and how to plug in your own credentials. Without **an SSH-reachable workstation with a browser + a small HTTP serve script**, this skill won't run — that's expected.

Push a file to your workstation for viewing in the browser. Usage: /push <file-path>

## Instructions

**If the file is Markdown (`.md`), render it first:**

```bash
bash ~/.claude/scripts/md2html.sh <file.md>               # prints the output .html path
bash ~/.claude/scripts/serve-to-workstation.sh <that.html>
```

Or as one line:

```bash
bash ~/.claude/scripts/serve-to-workstation.sh "$(bash ~/.claude/scripts/md2html.sh <file.md>)"
```

**Otherwise** (already-viewable HTML, PDF, image) just serve it:

```bash
bash ~/.claude/scripts/serve-to-workstation.sh <file-path>
```

Print the returned localhost URL for the user to open in their workstation's browser.

If no file path is provided, check if you just created a file the user would want to view (HTML, PDF, image, Markdown) and use that.

## Do not hand-author the HTML

When the user asks for a document "in HTML", write the **Markdown** and run `md2html.sh`. Do not emit a styled HTML page by hand: hand-authored HTML is more token-intensive and less consistent than deterministic rendering. The house stylesheet (light/dark, print-clean, scrolling tables) ships as `templates/doc.css` — installed at `~/.claude/templates/doc.css`. Change the look there, once, not per document.

Hand-authoring is only warranted when the page needs something Markdown cannot express: bespoke layout, interactive controls, a chart. In that case say so explicitly rather than doing it silently.

## Notes

- This pattern targets the common split where the agent runs on a headless `<dev-box>` (Linux, no GUI) while the user sits at a separate `<workstation>` (the machine with a browser). The serve script handles everything: it copies the file to a serve dir, starts a local HTTP server on `<dev-box>`, and sets up an SSH reverse tunnel so `<workstation>`'s browser can reach the listener over localhost.
- **Allowed roots.** The serve script takes an explicit allow-list of directories it will serve from; anything outside is refused with exit 2, so render or copy the file into one of them first. The reference list: `~/Projects/`, `~/.claude/projects/` (memory dirs), `/tmp/`, `<your-screenshots-dir>`, `~/.angel/` (review-run artifacts). Adapt the list to your layout — but keep it an allow-list. The script hands whatever path it's given to an HTTP server the workstation can reach; without the guard, one bad path argument publishes a secrets file or a whole home directory.
- Do NOT try to launch a browser remotely (e.g. `ssh <workstation> "powershell Start-Process ..."`) — that approach fails silently across the SSH boundary. The serve-then-tunnel pattern is the reliable path.
- `hooks/post-write-serve.sh` is a PostToolUse hook that auto-serves viewable files on Write, so a generated chart or report appears without an explicit `/push`. It is best-effort: on failure it reports the reason and never blocks the Write. It no-ops cleanly when no serve script is installed.

To adapt: write your own `serve-to-workstation.sh` that (1) rejects any path outside your allowed roots, (2) copies the target file into a web-served directory, (3) starts an HTTP server bound to a known port, (4) opens an SSH reverse tunnel from your workstation to that port (`ssh -R <port>:localhost:<port> -N -f <workstation>`), and (5) prints the `http://localhost:<port>/...` URL. Point the paths in this skill at your script.
