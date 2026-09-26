---
name: code
description: Delegate a concrete implementation, fix, refactor, or test task to one isolated Codex subagent and verify its structured result. Use when the user invokes code or explicitly asks to delegate coding work.
---

# Code

Explicit invocation authorizes one bounded delegation for the named task. It
does not authorize commits, pushes, destructive cleanup, external connectors,
or outbound messages.

1. Require a task description and a project directory. If either is missing,
   ask for it.
2. Read only project instruction files and the package/build command index needed
   to form the prompt. Do not read implementation source; the subagent owns that
   context.
3. Call Codex's native `spawn_agent` once. Use the current project as its working
   directory. Inherit the active model and reasoning effort; do not override
   either and do not ask the subagent to delegate again.
4. Give the subagent this contract:

```text
Implement the bounded task below in the current project.

TASK
<user task>

PROJECT INSTRUCTIONS
<applicable instruction files and known validation commands>

CONSTRAINTS
- Read relevant source before editing and follow project testing rules.
- Change only what the task requires and leave changes unstaged.
- Do not commit, push, publish, send messages, use external connectors, or run
  destructive git commands.
- Run the most specific tests, then the project validation command when one is
  available.
- After three failed repair attempts, stop and report the attempts and likely
  root cause.

Return exactly these headings:
### Summary
### Files changed
### Tests
### Validation
### Blockers
Each test or validation claim must include the command and observed result.
```

5. Wait for completion. Inspect the working-tree diff and the cited test output
   before relaying success. If the result is missing a required heading or its
   evidence cannot be verified, report that gap rather than laundering the
   claim.
6. Return the five sections, corrected for observed evidence. Leave all changes
   unstaged.
