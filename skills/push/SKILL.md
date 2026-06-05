---
name: push
description: Serve a local file to a workstation browser over an SSH tunnel (integration stub).
---
> **INTEGRATION STUB.** This skill wires Claude Code to an external tool/account that you must supply and configure: **an SSH-reachable workstation with a browser + a small HTTP serve script (serve-to-workstation)**. It ships as a working example of the integration pattern, not a turnkey feature. See `docs/integrations.md` for what to install and how to plug in your own credentials. Without **an SSH-reachable workstation with a browser + a small HTTP serve script**, this skill won't run — that's expected.

Push a file to your workstation for viewing in the browser. Usage: /push <file-path>

## Instructions

Run `bash ~/.claude/scripts/serve-to-workstation.sh <file-path>` and print the returned localhost URL for the user to open in their workstation's browser.

If no file path is provided, check if you just created a file the user would want to view (HTML, PDF, image) and use that.

This pattern targets the common split where the agent runs on a headless `<dev-box>` (Linux, no GUI) while the user sits at a separate `<workstation>` (the machine with a browser). The serve script handles everything: it copies the file to a serve dir, starts a local HTTP server on `<dev-box>`, and sets up an SSH reverse tunnel so `<workstation>`'s browser can reach the listener over localhost.

Do NOT try to launch a browser remotely (e.g. `ssh <workstation> "powershell Start-Process ..."`) — that approach fails silently across the SSH boundary. The serve-then-tunnel pattern is the reliable path.

To adapt: write your own `serve-to-workstation.sh` that (1) copies the target file into a web-served directory, (2) starts an HTTP server bound to a known port, (3) opens an SSH reverse tunnel from your workstation to that port (`ssh -R <port>:localhost:<port> -N -f <workstation>`), and (4) prints the `http://localhost:<port>/...` URL. Point the path in this skill at your script.
