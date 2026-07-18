---
name: gmail
description: Create Gmail drafts/sends via a local email-CLI wrapper (integration stub). Draft-by-default with a sanitizer + clobber-guard.
---
> **INTEGRATION STUB.** This skill wires Claude Code to an external tool/account that you must supply and configure: **a Gmail/Google Workspace CLI (the real setup uses a `gws`-style CLI wrapped by a local `~/bin/gmail` script) + your Google account**. It ships as a working example of the integration pattern, not a turnkey feature. See `docs/integrations.md` for what to install and how to plug in your own credentials. Without **a Gmail/Google Workspace CLI + your Google account**, this skill won't run — that's expected.

Create Gmail drafts and sends via a local `<your-email-cli>` wrapper (the example setup uses a `~/bin/gmail` script wrapping a `gws`-style Google Workspace CLI). Mandatory for any Gmail interaction — handles encoding, line wraps, threading, and sanitizer checks that would otherwise fail.

## Instructions

Always use `<your-email-cli>` for Gmail draft creation, sends, AND deletes. Never hand-roll RFC-822 with Python's `email` library or call the underlying `gws gmail users drafts create` / `messages send` / `drafts delete` directly — the wrapper wraps them, with mandatory sanitizer checks (create/send) and a clobber-guard (delete/update) that prevent recurring failure modes.

Subcommands (the example wrapper is invoked as `gmail`):
- `gmail draft` — create or update a draft (default for the "drafts not send" rule). `--update <id>` is **guarded** (see below).
- `gmail send` — send immediately (sanitizer still mandatory; use sparingly — prefer drafts)
- `gmail delete --draft-id <id>` — delete a draft, **guarded against clobbering your edits** (see below). ALWAYS use this; never raw `gws ... drafts delete`.
- `gmail check` — run sanitizer only, no API call (useful for pre-flighting copy-pasted text)

## Clobber guard — deleting / updating a draft you created earlier

You may edit drafts in the Gmail web UI and send them without telling the agent. A draft handed to you on a prior turn has an **extremely high likelihood of having changed.** The wrapper defends against silently destroying those edits:

- On `draft` create/update, the tool records the body it wrote under `~/.config/gmail-tool/`.
- `gmail delete` and `gmail draft --update` re-read the **live** draft first and **REFUSE** (exit 2, with a diff) if it differs from what the tool wrote — i.e. if you edited it. Pass `--force` only after confirming.
- Gmail `drafts.delete` is **permanent** (no Trash). **NEVER** delete or supersede a draft via raw `gws gmail users drafts delete` — that bypasses the guard. A PreToolUse hook can block the raw form; use `gmail delete`.

```
gmail delete --gws-config ~/.config/gws-<your-company> --draft-id r1234567890
```

To supersede a draft, prefer `gmail draft --update <id>` (in-place, guarded) over create-new-then-delete-old.

## Common patterns

**Simple draft to a secondary account:**
```
gmail draft --gws-config ~/.config/gws-<your-company> \
  --to recipient@example.com \
  --subject "Subject text" \
  --body-file /tmp/body.txt
```

**Threaded reply** (preserves In-Reply-To, References, threadId):
```
gmail draft --gws-config ~/.config/gws-<your-company> \
  --to helpdesk@example.com --cc original-sender@example.com \
  --subject "Re: original subject" \
  --body-file /tmp/reply.txt \
  --reply-to-msg-id <gmail-message-id-of-source>
```

**Standalone reply** (visible in Drafts label, not nested under thread):
Add `--no-thread` to the above. Recipient-side threading still works via the In-Reply-To/References headers.

**Force-send** (sanitizer still runs):
Use `gmail send` with the same args (no `--update`). The "drafts not send" default means this should be rare and explicit.

## Defaults

- Body: write to `/tmp/body-<descriptor>.txt` and pass `--body-file` (avoids shell-quoting hell)
- Account: pass `--gws-config` explicitly. Default is whatever `GOOGLE_WORKSPACE_CLI_CONFIG_DIR` env points to. For multiple Workspace accounts, keep one config dir per account (e.g. `~/.config/gws-<your-company>`).
- Subject and body: tool transliterates non-ASCII (em-dash → `--`, smart quotes → straight) for max portability — a fine default. Pass `--keep-utf8` if you specifically want to preserve accents/em-dashes: the **body** goes out as `charset=utf-8` 8bit, and the **subject** is RFC-2047-encoded (`=?utf-8?…?=`) so an em-dash subject or an accented name renders correctly in Gmail and recipient clients. This is a case worth testing explicitly the first time you wire up `--keep-utf8` in your own wrapper — a naive subject-encoding helper can return raw undecoded unicode instead of the RFC-2047 form, producing mojibake (`â€"`) that only shows up once a real message lands in an inbox. Cheap insurance after any non-ASCII subject: confirm the on-the-wire header with `gws gmail users messages get --params '{"userId":"me","id":"<msg-id>","format":"raw"}'` and check the `Subject:` line is `=?utf-8?…?=` — the `metadata` format auto-decodes the header, so use `raw` to catch a raw-bytes regression. The sanitizer checks your input, not the tool's own output, so it won't catch a bug in your own encoding path.
- Sanitizer warnings block by default. Pass `--ack-warnings` to proceed. Use `--dry-run` to preview without API call.

## Failure modes the tool eliminates

These are the recurring problems that motivated the wrapper — never re-introduce them by going around:

- `email.message.EmailMessage.set_content()` quoted-printable encodes UTF-8 and hard-wraps at 78 chars, breaking commands and URLs
- Forgetting RFC-2047 on Subject → recipient sees `â€"` artifacts for em-dashes
- Forgetting `Content-Transfer-Encoding: 8bit` → same as above
- Hand-fabricating In-Reply-To headers → broken threading on recipient side
- Manually pre-wrapping prose at 80 chars → format=flowed clients can't reflow
- Mojibake (`â€"`, `Ã©`, etc.) silently sent through — recipient sees garbage
- Backslash line-continuation in commands → recipient's mail client may break them
- "Re:" subject without `--reply-to-msg-id` → looks like a reply but isn't threaded

All caught by the sanitizer. Don't go around it.

## When NOT to use the tool

- Sending an existing draft built in the Gmail web UI: that draft never went through the sanitizer, so use raw `gws gmail users drafts send` only if you explicitly want that bypass.
- Bulk operations (>10 drafts at once): the wrapper isn't optimized for that; confirm before doing it.
