# Security Policy

## Reporting a vulnerability

If you've found a security issue in NineAngel — particularly a working prompt-injection vector against any persona, the integrator, or the fix-batch dispatch — please report it privately rather than filing a public issue.

Use GitHub's [private security advisory](https://github.com/PropterMalone/NineAngel/security/advisories/new) feature. Public issues for security bugs can disclose attack details before a fix lands.

## Scope

NineAngel is an LLM tool that processes untrusted code — any project the user invokes `/angel` against is the trust boundary. The threat model is documented in `DESIGN.md` (§Untrusted-content handling). Reports of particular interest:

- **Prompt-injection vectors** that bypass the `<project_context>` / `<changes_to_review>` envelopes and alter persona behavior (suppressing findings, fabricating findings, redirecting persona scope).
- **Persona-output injection** that survives the integrator's Phase-0 sanitization despite mimicking instructions.
- **Fix-batch dispatch surfaces** that allow shell-execution despite the per-finding "code changes only" preamble.
- **Filesystem read paths** that exfiltrate content outside the project root (symlink follow, path traversal in persona file lookups, etc.).
- **Cross-project contamination** in the per-project fix-batch storage that allows one project's batch to be applied against another.

Out of scope:

- Vulnerabilities in Claude Code itself (report upstream).
- Vulnerabilities in projects that NineAngel reviews (those are the project's own concern).
- Performance / cost issues that don't have a security impact.

## Run archive sensitivity and retention

`~/.angel/runs/` holds verbatim findings from every NineAngel review, including vulnerability reports, PII-sweep outputs, and de-anonymization attack results on reviewed projects. **Never sync or publish this directory.**

- Do not include it in cloud backups that sync to untrusted storage (iCloud, Google Drive, Dropbox in a shared account).
- Do not commit it to any git repository, including private ones.
- The `pii-registry.md` files in per-project memory dirs (`~/.claude/projects/*/memory/pii-registry.md`) are similarly sensitive — field-level maps of where identifiers live in a project.
- **Policy registries** for domain angels are more sensitive still: they contain engagement-specific rules and attribution boundaries. Keep them in the gitignored project-memory tree. Never relocate one into a tracked path, quote one into a public run report, or include private policy text in a persona file (persona files ship publicly; registries do not).

**Retention rule:**
- **Never delete** dispositioned runs (those with a `dispositions.json`). These are the precision-measurement corpus; deleting them silently corrupts the per-persona value table.
- **Never delete** non-experiment runs from the last 6 months. These are active calibration data.
- **Archive, don't delete** older runs: if disk space is a concern, move them to cold storage rather than deleting. Their `findings-snapshot.json` + `findings/*.md` are rebuildable only from the run dir itself.
- Experiment runs (runs with `EXPERIMENT` marker or `cal:` key in usage.log) may be pruned after their calibration period concludes and results are recorded in the relevant ADR.

## Response

Best-effort triage within 7 days. No SLA — this is a personal-tool project shipping publicly under MIT. Reporters who want acknowledgment in the fix's commit message or CHANGELOG should say so in their report.
