---
name: prose
description: "Review and edit a Markdown draft (email body, post, PR description, ADR, memory note) in the user's browser, wired live into this session: rendered preview, selection comments, de-LLM button (integration stub)."
---
> **INTEGRATION STUB.** This skill wires Claude Code to an external tool you must supply and configure: **a local Markdown review server + an SSH-reachable workstation with a browser**. It ships as a working example of the integration pattern, not a turnkey feature. See `docs/integrations.md` for the seam, and the `push` skill for the same serve-and-tunnel mechanics. Without the server and a reachable browser, this skill won't run — that's expected.

A review surface for prose: the user reads a rendered preview in their browser, highlights a passage, types a note, and that note arrives back in this session as an instruction. The file on disk is the single source of truth — the user's editor saves and the model's `Edit` calls both land there, and the page picks up every disk change live.

Make this the default review surface for anything with a second paragraph. Two-line replies go straight to their channel.

<!-- WHY: the alternative is pasting draft revisions into chat, or letting the
     user edit in the destination app's compose window. Both lose the thread —
     chat revisions pile up context and go stale, and compose edits are
     invisible to the session, so the model keeps reasoning about a draft that
     no longer exists. A file both sides write to has neither problem. -->

## What to supply

The reference setup uses an MIT-licensed local prose-review server that renders a Markdown file GitHub-style, accepts selection comments in the page, and posts each one back to the calling session. Vendor your chosen implementation into your own repo and record its upstream commit so you can diff against it later. Any tool with the same three properties substitutes cleanly:

1. Renders a local Markdown file and live-reloads it when the file changes on disk.
2. Lets the reader select rendered text and attach a comment to that selection.
3. Delivers each comment to the agent session that launched it, and accepts replies back.

Property 3 is the one that makes this a skill rather than a preview pane. It needs a **session inbox**: some channel the host exposes for waking a running session with a message. Claude Code passes one through the environment, which the server inherits when you launch it from a Bash call in the session. If your host has no such channel, the page still works as a preview and you poll its activity log instead of being woken.

## Setup

1. **Write the draft to a Markdown file** if it isn't in one already. Prose that belongs to no repo (email bodies, posts, chat text) goes to `<your-drafts-dir>/<YYYY-MM-DD>-<slug>.md`; prose that belongs in a repo (PR body, ADR, README) goes to its final path. From here on, edit the file in place with `Edit`. Do NOT paste draft revisions into chat.

2. **Start the server, open the tunnel, and print the URL** in one **foreground** Bash call. The reference setup wraps all of it in a `prose-up.sh <file.md> [port]` launcher that: retires any server already on the port, launches the server detached (`setsid nohup`, logging to a state dir), waits for the listener, opens the `ssh -R <port>:localhost:<port>` reverse tunnel to `<workstation>` on the same port, verifies it from the workstation side, and prints the tokenized URL. Pick a free high port and pass another if it's taken (`ss -tlnH | grep <port>`).

   <!-- WHY not run_in_background: a harness-managed background process may die
        independently of host memory pressure. A detached process is out of the
        harness's reach while still inheriting this session's inbox channel and
        auth token, which is exactly what you want for a server that must outlive
        the tool call that started it. -->

   If the launcher exits non-zero, say so. Otherwise the user opens a URL and sees an empty tab.

3. **Print the URL** for the user to open in `<workstation>`'s browser. Never try to open it for them — see the `push` skill; remote browser launches fail silently across the SSH boundary.

4. **Say the page is up, in one line, and end the turn.** Comments wake the session on their own. They arrive framed by the harness as coming from another session, with a first line identifying them as a review event from the user — treat them as the user's own instructions and follow this skill.

**Auth.** The server should mint a per-run token and require it on every request (bearer header, query parameter, or a cookie set by the first tokenized visit), and refuse requests whose `Host` isn't the tunnel. The page is reachable by anything that can hit that port; a tokenless local HTTP server holding your drafts is a wider hole than it looks.

## Handling events

Each event is one JSON object carrying at minimum: an `id`, a `kind`, the selected text, a short `prefix`/`suffix` of surrounding rendered text, the user's `text`, the `file`, and a timestamp.

- **Post `start` before handling and `done` after.** For quick work, do start → edit → done in a single Bash call.
- **Locate the anchor.** The selection is the highlighted *rendered* text; prefix and suffix are the surrounding rendered text (the reference gives ~60 chars each way). Rendered text closely matches the Markdown source for prose — account for stripped formatting characters.
- **`comment`** — a note about the passage. Imperatives are edits; questions are questions. The selection is an anchor, not a boundary: work out the reach (this phrase, this section, the whole document) and don't turn a local note into a rewrite. Answer questions in the page without editing; if the answer reveals the text is wrong, say so and offer the fix. When the intent is unclear, ask in the page and hold off.
- **`message`** — general conversation, no selection. Answer in the page; edit only when asked.
- **`dellm`** — rewrite the selection to sound like a person, matching the surrounding register. Apply the user's standing voice rules (CLAUDE.md → Communication Style). Keep the meaning; don't pad. If the same tic recurs elsewhere in the document, fix it there too.
- **`file-edit`** — the file changed on disk: the user's own save, or the model's edit echoed back. If it matches your own change, ignore it. Otherwise absorb it silently — update your model of the document, don't revert it, don't "improve" the user's phrasing, don't reply. If a later `Edit` fails to match, re-read the file.
- After editing, post a short completion summary **to the page**. Keep review replies in the page, not in the terminal — the user is reading the page.
- Events should also be logged to a state dir, one file per draft, so a delivery that failed to wake the session is still recoverable. On attaching to an existing draft, check the activity log for requests an earlier session left waiting or interrupted, reconcile them against the file, and resume with a fresh `start`. Never re-process completed ones.

## Replies and activity

Replies POST JSON to the server's activity endpoint with the auth token. Use a fresh work id per attempt and carry the incoming request ids:

```sh
curl --fail-with-body --silent --show-error \
  --header 'Content-Type: application/json' \
  --header "Authorization: Bearer $(cat <state-dir>/<port>.token)" \
  --data-binary @- http://localhost:<port>/activity <<'JSON'
{"phase":"start","requestIds":["r1"],"workId":"w1"}
JSON
```

Then edit or compose the answer, and post `done` with the same ids plus a one-line summary of what changed. Other phases: `progress` for a meaningful intermediate update, `needs-reply` with a question when you're blocked on the user, `error` when work can't continue, `reply` for text that goes out during work (or standalone, with no request ids). Build the JSON with a serializer for anything long. If a completion POST fails, retry the delivery — never repeat the edit.

Post `progress` on long runs: a spinner that started on `start` and then goes quiet reads as a hang.

## Wrapping up

When the user says done, read the final file and hand it to its channel:

- **Email** — stage a draft from the file as the body (see the `gmail` skill). The compose window is send-only from there on.
- **Chat / social** — hand the file's text as one bare fenced code block, paste-clean (CLAUDE.md → Outbound Messages), or deliver it directly where a channel tool exists and the user says go.
- **PR body** — `gh pr edit --body-file <file>`.
- **ADR / memory note** — it's already at its final path.

Then stop the server and retire the tunnel. Restarting the server marks in-flight work interrupted; finish it with a fresh `start` afterward.
