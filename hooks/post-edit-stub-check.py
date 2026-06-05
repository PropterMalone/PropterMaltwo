#!/usr/bin/env python3
"""PostToolUse hook: scan edited/written files for stub patterns.

Catches TODO, FIXME, pass, unimplemented!(), and similar stubs that
indicate incomplete implementation. Silent on clean files.

Inspired by dollspace.gay's Chainlink hooks system.
"""

import json
import re
import sys

CODE_EXTENSIONS = {
    ".ts", ".tsx", ".js", ".jsx", ".py", ".rs", ".go", ".java", ".sh",
}

# Each tuple: (compiled regex, human-readable label)
STUB_PATTERNS = [
    (re.compile(r"\bTODO\b", re.IGNORECASE), "TODO comment"),
    (re.compile(r"\bFIXME\b", re.IGNORECASE), "FIXME comment"),
    (re.compile(r"\bHACK\b", re.IGNORECASE), "HACK comment"),
    (re.compile(r"^\s*pass\s*$"), "bare pass statement"),
    (re.compile(r"^\s*\.\.\.\s*$"), "bare ellipsis (stub)"),
    (re.compile(r"\bunimplemented!\(\)"), "unimplemented!() macro"),
    (re.compile(r"\btodo!\(\)"), "todo!() macro"),
    (re.compile(r"raise\s+NotImplementedError\(\s*\)"), "bare NotImplementedError()"),
    (re.compile(r"throw\s+new\s+Error\(\s*['\"]not\s+implemented", re.IGNORECASE), "throw not-implemented error"),
    (re.compile(r"//\s*implement\s+(later|this|here)", re.IGNORECASE), "implement-later comment"),
    (re.compile(r"#\s*implement\s+(later|this|here)", re.IGNORECASE), "implement-later comment"),
]


def get_file_path(tool_input: dict) -> str | None:
    return tool_input.get("file_path")


def has_code_extension(path: str) -> bool:
    for ext in CODE_EXTENSIONS:
        if path.endswith(ext):
            return True
    return False


def scan_text(text: str) -> list[tuple[int, str, str]]:
    """Return list of (line_number, matched_text, label) for stub findings."""
    findings = []
    for line_num, line in enumerate(text.splitlines(), 1):
        for pattern, label in STUB_PATTERNS:
            if pattern.search(line):
                findings.append((line_num, line.rstrip(), label))
                break  # one finding per line
    return findings


def get_new_content(tool_input: dict) -> str | None:
    """Extract only the newly written content from the tool input."""
    # Write tool: full file content
    if "content" in tool_input:
        return tool_input["content"]
    # Edit tool: just the replacement text
    if "new_string" in tool_input:
        return tool_input["new_string"]
    return None


def main() -> None:
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        return

    tool_input = hook_input.get("tool_input", {})
    file_path = get_file_path(tool_input)

    if not file_path:
        return

    # skip .claude/ paths and non-code files
    if "/.claude/" in file_path:
        return
    if not has_code_extension(file_path):
        return

    content = get_new_content(tool_input)
    if not content:
        return

    findings = scan_text(content)
    if not findings:
        return

    lines = [f"Stub/incomplete code detected in {file_path} (new content):"]
    for line_num, text, label in findings:
        lines.append(f"  [{label}]: {text.strip()}")
    lines.append("")
    lines.append("Address these before considering the implementation complete.")

    output = {"additionalContext": "\n".join(lines)}
    json.dump(output, sys.stdout)


if __name__ == "__main__":
    main()
