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

## Response

Best-effort triage within 7 days. No SLA — this is a personal-tool project shipping publicly under MIT. Reporters who want acknowledgment in the fix's commit message or CHANGELOG should say so in their report.
