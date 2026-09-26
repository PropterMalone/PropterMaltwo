---
name: code
description: Delegate a concrete implementation, fix, refactor, or test task to Polytoken's shipped general-purpose subagent and verify its structured completion. Use when the user invokes code or explicitly asks to delegate coding work.
---

# Code

Explicit invocation authorizes one bounded delegation for the named task. It
does not authorize commits, pushes, destructive cleanup, external connectors,
or outbound messages.

1. Require a task description and project directory. Ask if either is missing.
2. Read only project instruction files and the package/build command index needed
   for the prompt. Leave implementation-source discovery to the subagent.
3. Call the shipped `subagent` tool with `general-purpose`, `count: 1`, and the
   project directory as `cwd`. Do not select or pin a provider/model. Do not copy,
   install, or override a subagent definition, and prohibit nested delegation.
4. Give the subagent this contract:

```text
Implement the bounded task below in the current project.

TASK
<user task>

PROJECT INSTRUCTIONS
<applicable instruction files and known validation commands>

CONSTRAINTS
- Read relevant source before editing and follow project testing rules.
- Change only what the task requires.
- Do not delegate again, commit, push, publish, send messages, use external
  connectors, or run destructive git commands.
- Run the most specific tests, then the project validation command when present.
- After three failed repair attempts, stop and report each attempt and the likely
  root cause.

Return through the structured completion sink with summary plus files containing
changed paths. In summary use exactly these headings:
### Summary
### Tests
### Validation
### Blockers
Each test or validation claim must include the command and observed result.
```

5. The launch returns an asynchronous job handle. Let auto-drain deliver the
   completion notification, or use job status/result tools when the user asks for
   an update. Do not duplicate the delegated work while it runs.
6. On completion, inspect the working-tree diff and cited evidence. Treat a failed
   subagent notification as failure, not a successful apology or partial pass.
   Return the structured summary with any verification gaps. Leave changes
   unstaged.
