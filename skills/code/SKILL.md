---
name: code
description: Delegate a coding task to a subagent. Keeps coding output (file reads, test runs, diffs) out of main context. Usage: /code <task description>
---

Delegate a coding task to a subagent that handles implementation, testing, and validation.

## 1. Validate context

- You must be in a project directory (`~/Projects/*`, or wherever your repos live — adapt to your layout). If not, ask the user which project.
- Args are required — the task description. If empty, ask what to build/fix.

## 2. Gather project context

Read these (parallel) to build the subagent prompt:
- Project CLAUDE.md (if it exists in the project root)
- `package.json` scripts section (to know validate/test/build commands)

Do NOT read source files — the subagent will do that.

## 3. Compose and launch subagent

Use the Agent tool with this prompt structure:

```
You are implementing a coding task. Your working directory is {project_dir}. All file paths are relative to this directory.

## Task
{user's task description}

## Project context
{project CLAUDE.md contents, if any}

## Available commands
{scripts from package.json, or defaults: npm run validate, npm test, npm run build}

## Instructions
1. Read relevant source files to understand the codebase before making changes.
2. Follow TDD: write a failing test first, then implement, then refactor.
3. After implementation, run the project's validate command (or `npm run validate`).
4. If validate fails, fix the issue. After 3 failed fix attempts, STOP and report with: what you tried each time, the error each time, and what you think the root cause is.
5. Do NOT commit. Leave changes unstaged.

## Scope
- Only change what is necessary for the task. Do not refactor, add comments, add type annotations, or improve surrounding code.
- Do not run git commands (status, log, diff, etc.). Do not read documentation files (README, CHANGELOG) unless directly relevant to the task.
- Use only file, search, bash, and edit tools. Do not use MCP tools.

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

Relay the subagent's structured summary to the user verbatim. Do not editorialize unless there are blockers that need a decision.

If the user wants to commit the changes, use `/commit` or handle normally — the changes are on disk.
