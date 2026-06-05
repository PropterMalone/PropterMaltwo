---
name: status
description: One-shot dashboard of live background work — tmux sessions, queued background jobs, scheduled triggers, /loop crons, long-running processes, and in-session background tasks. Cheap, non-interactive. Use when orienting mid-session, after a gap, or when the user asks "what's running".
---

Report on everything running in the background. Goal: one compact block the user can read in five seconds.

## 1. Collect in parallel

Fire all of these at once — do NOT serialize. Each is cheap and independent.

### tmux sessions
```bash
tmux list-sessions 2>/dev/null
```
For any session whose name suggests long-running work (matches `download|embed|run-|batch|job|etl|watch`), capture the last 10 lines:
```bash
tmux capture-pane -pS -10 -t <session-name>
```

### Background job queue (optional — only if you run one)
If you have a local job-queue tool, list its pending/running/recent items here. Example with a `<your-queue-tool>` CLI:
```bash
# Example — adapt to your own queue tool, or delete this block if you have none.
cd <your-queue-tool-dir> && <your-queue-tool> queue list 2>&1 | head -30
```
Note anything queued, in-progress, or recently completed. Flag overdue items. (If your queue CLI resolves dependencies relative to cwd — e.g. `tsx` does — `cd` into its directory first; running it from an absolute path can fail silently.)

### Scheduled triggers (remote agents)
Use `RemoteTrigger` tool with `action: list`. Report:
- Active triggers with their next fire time
- Most recent run result per trigger

### In-session crons
Use `CronList` tool. These are `/loop` or one-shot schedules created this session.

### Long-running processes

Bound elapsed time to 10 min – 24 h to catch active work without drowning in machine-lifetime daemons:
```bash
ps -eo pid,etimes,cmd --sort=-etimes 2>/dev/null | awk 'NR==1 || ($2 > 600 && $2 < 86400)' | grep -v -E '\[|systemd|dbus|Xorg|gnome|pulse|pipewire|cups|tracker|evolution|gvfs|ibus|at-spi|goa-daemon|tailscaled|docker-|containerd|postgres|chromium|firefox|sshd|NetworkManager|udisksd|ModemManager|polkitd|snapd|rtkit|fwupd|packagekit|avahi|wpa_supplicant|rsyslogd|cron|agetty|login|bash$|zsh$|sh$|sleep|tmux:|screen|openbox|wireplumber|lightdm|s6-|dumb-init|cloudflared|syncthing|ollama|vnstatd|networkd-dispatcher|bluetoothd|unattended-upgrade|nginx|colord|accounts-daemon|multipathd' | head -30
```
Look for: `node`, `python`, `claude`, `curl`, `rsync`, orphaned `ssh -R` tunnels from past sessions, stray dev servers.

### In-session bash/agent tasks
Mentally scan the tool-use history: any Bash with `run_in_background: true`, any Agent with `run_in_background: true`, any Monitor still active. The harness tracks these — if you need an explicit list, the `/tasks` slash command shows them, but for `/status` just report what you kicked off this session.

## 2. Systemd user units (occasional — only if triggered)

Skip unless the user says "include services" or a session has recently touched systemd config. Then:
```bash
systemctl --user list-units --type=service --state=running --no-legend
systemctl --user list-units --state=failed --no-legend
```

## 3. Report

Compact format, skip empty sections:

```
**Background:**
- tmux: <session> — <status snippet>  (repeat per live session)
- Queue: N queued, M running — next: <task name or none>   (only if you run a queue)
- Triggers: N active, next fire <when>, last <trigger> <status>
- In-session crons: <summary or none>
- Processes: <pid> <etime> <cmd> — (only if unexplained or >1h old)
- Background tasks: <what I launched this session, and status>

Flags: <anything overdue, failed, unexplained, or needing attention>
```

If nothing's running anywhere, just say "Background: nothing active." and stop.

## 4. Notes

- This skill is read-only. Never kill, restart, or modify anything. If the user wants to act on something surfaced here, they'll say so.
- If a probe fails (queue CLI path moved, tmux not installed, etc.), note it silently and continue with the others. Don't block the report on any single probe.
- For very long-running jobs (overnight batches, multi-day downloads), include a rough percent-done or elapsed-time estimate if the tmux capture makes it obvious.
