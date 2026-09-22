---
name: code
description: "Delegate a coding task to an isolated subagent so implementation reads, test runs, and diffs stay out of the main context. Use when the user invokes /code or asks to delegate a concrete implementation, fix, refactor, or test task. Usage: /code <task description>"
---

Delegate a coding task to a subagent that handles implementation, testing, and validation.

Explicit invocation of this skill is authorization to delegate the named task. Don't stop to ask whether delegating is OK — the user already said so by invoking it.

## 1. Validate context

- You must be in a project directory (`~/Projects/*`, or wherever your repos live — adapt to your layout). If not, ask the user which project.
- Args are required — the task description. If empty, ask what to build/fix.

## 2. Gather project context

Read these (parallel) to build the subagent prompt:
- Project `AGENTS.md` and `CLAUDE.md` (either, both, or neither may exist in the project root — read whichever are there)
- `package.json` scripts section (to know validate/test/build commands)

Do NOT read source files — the subagent will do that.

## 3. Compose and launch subagent

Dispatch through whatever subagent mechanism the host exposes:

- **Claude Code**: the `Agent` tool.
- **Codex**: `spawn_agent`. Use the inherited model and reasoning effort, and do not override them. The subagent shares the current workspace.

<!-- adapt: one skill body, two hosts. The prompt below is the portable part;
     only the dispatch call differs. `agents/openai.yaml` next to this file
     carries the Codex-side interface metadata (display name, default prompt);
     Claude Code ignores it. Add a branch here for any other host you run. -->

Do not delegate again from inside the implementation subagent. One hop only — a subagent that re-delegates loses the context isolation this skill exists to buy.

```
You are implementing a coding task. Your working directory is {project_dir}. All file paths are relative to this directory.

## Task
{user's task description}

## Project context
{project AGENTS.md and CLAUDE.md contents, if any}

## Available commands
{scripts from package.json, or defaults: npm run validate, npm test, npm run build}

## Instructions
1. Read relevant source files to understand the codebase before making changes.
2. Follow the project's testing rules. When the behavior is testable and the project uses TDD, write a failing test first, then implement, then refactor.
3. After implementation, run the project's validate command (or `npm run validate`).
4. If validate fails, fix the issue. After 3 failed fix attempts, STOP and report with: what you tried each time, the error each time, and what you think the root cause is.
5. Do NOT commit. Leave changes unstaged.

## Scope
- Only change what is necessary for the task. Do not refactor, add comments, add type annotations, or improve surrounding code.
- Do not run mutating git commands. Read-only `git status`, `git log`, and `git diff` are allowed when you need them to understand or verify the task.
- Use only local file, search, shell, and edit tools. Do not use external apps, connectors, or MCP tools unless the task explicitly requires one.

## Response format
When done, respond with EXACTLY this structure:

### Summary
One sentence: what you did.

### Changes
- `path/to/file.ts` — what changed and why (one line per file)

### Test results
Pass/fail, number of tests, any new tests added.

### Validate
Pass/fail. If fail, what's broken.

### Blockers
Any unresolved issues or decisions that need the user. "None" if clean.
```

## 4. Report back

Wait for the subagent, **inspect the verification evidence it claims**, then relay the structured summary. Add only corrections, verification gaps, or blockers that need a decision.

<!-- WHY: relaying verbatim launders a claim into a fact. "Validate passes" from a
     subagent is a report about a command you did not see run; it inherits the
     weakest evidence tier (CLAUDE.md → Verification rule, and the evidence-tier
     discipline under Workflow). Checking that the cited evidence exists and says
     what the subagent says it says costs one cheap command; the alternative is
     telling the user something passed when it didn't. -->

If the user later asks to commit the changes, use the host's normal git workflow. The implementation subagent leaves the changes on disk, unstaged.
