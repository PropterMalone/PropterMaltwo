# Claude Code host setup

Claude Code is a **first-class** PropterMaltwo host and remains the compatibility
baseline. It supports only the `full` profile.

## Prerequisites and install

- Claude Code installed and authenticated.
- A writable `CLAUDE_HOME` (default `~/.claude`).

```bash
./install.sh                                  # legacy dry run: Claude full
./install.sh --apply                          # legacy apply: Claude full
./install.sh --host claude-code --profile full
./install.sh --host claude-code --profile full --apply
```

The full profile mirrors the repository's existing Claude surface: `CLAUDE.md`,
rules, all canonical skills and hooks, templates, scripts, docs, statusline, and
settings example. It preserves legacy backup-and-replace behavior. An existing
`settings.json` is never overwritten; when absent, it is seeded from
`settings.example.json`.

## Paths and merge points

- Instructions and assets: `$CLAUDE_HOME`.
- Existing mirrored files that differ receive immutable pre-install backups.
- `settings.json` is the manual merge point; compare it with
  `$CLAUDE_HOME/settings.example.json`.

## Verify

```bash
./install.sh --host claude-code --profile full --doctor
bash hooks/test-hooks.sh
python3 hooks/test-gh-identity-hooks.py
```

Doctor reports static support separately from local activation. A configured
hook is not called active unless a host-runtime check recorded
`verified-active`.

## Known gaps and optional integrations

Claude-specific auto-memory, transcript workflows, statusline telemetry,
`claude -p`, and the full skill collection remain in this host only. Email,
task, browser, MCP, notifications, and scheduled work require the optional tools
and credentials described in [Integrations](../integrations.md).

## Rollback and uninstall

Preview the operation first:

```bash
./install.sh --host claude-code --profile full --uninstall
./install.sh --host claude-code --profile full --uninstall --apply
```

Uninstall removes unchanged managed files and restores the original saved file
when the installer replaced one. It preserves modified installed files and
reports them. Follow any recovery command exactly if doctor reports an unresolved
transaction journal. For legacy compatibility, a visible timestamped backup is
created before replacing a differing mirrored file; if a later transaction step
fails, rollback restores the managed destination but may leave that extra
preservation copy under `$CLAUDE_HOME`.
