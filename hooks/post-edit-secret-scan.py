#!/usr/bin/env python3
"""PostToolUse hook: scan edited/written files for hardcoded secrets.

Detects AWS keys, private keys, API key assignments, password assignments,
connection strings with embedded passwords, and hardcoded JWTs.
Silent on clean files. Excludes example/placeholder values.

Inspired by dollspace.gay's Chainlink hooks system.
"""

import json
import re
import sys

SCAN_EXTENSIONS = {
    ".ts", ".tsx", ".js", ".jsx", ".py", ".rs", ".go", ".java", ".sh",
    ".yaml", ".yml", ".toml", ".json", ".env",
}

# Lines containing these words are likely examples, not real secrets
EXCLUSION_WORDS = {
    "example", "placeholder", "changeme", "your_", "your-", "xxx",
    "replace_me", "insert_", "dummy", "test_key", "fake",
}

# Each tuple: (compiled regex, human-readable label, is_critical)
SECRET_PATTERNS = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key", True),
    (re.compile(r"-----BEGIN\s+(RSA|DSA|EC|OPENSSH|PGP)\s+PRIVATE\s+KEY-----"), "private key", True),
    (re.compile(r"""(?:api[_-]?key|apikey)\s*[:=]\s*['"][A-Za-z0-9_\-]{16,}['"]""", re.IGNORECASE), "API key assignment", False),
    (re.compile(r"""(?:password|passwd|pwd)\s*[:=]\s*['"][^'"]{8,}['"]""", re.IGNORECASE), "password assignment", False),
    (re.compile(r"""(?:secret|token)\s*[:=]\s*['"][A-Za-z0-9_\-/+=]{16,}['"]""", re.IGNORECASE), "secret/token assignment", False),
    (re.compile(r"(?:mongodb|postgres|mysql|redis)://\S+:\S+@"), "connection string with credentials", False),
    (re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"), "hardcoded JWT", False),
]


def get_file_path(tool_input: dict) -> str | None:
    return tool_input.get("file_path")


def has_scan_extension(path: str) -> bool:
    for ext in SCAN_EXTENSIONS:
        if path.endswith(ext):
            return True
    return False


def is_excluded_line(line: str) -> bool:
    lower = line.lower()
    return any(word in lower for word in EXCLUSION_WORDS)


def scan_text(text: str) -> list[tuple[int, str, str, bool]]:
    """Return list of (line_number, matched_text, label, is_critical)."""
    findings = []
    for line_num, line in enumerate(text.splitlines(), 1):
        if is_excluded_line(line):
            continue
        for pattern, label, critical in SECRET_PATTERNS:
            if pattern.search(line):
                findings.append((line_num, line.rstrip(), label, critical))
                break
    return findings


def get_new_content(tool_input: dict) -> str | None:
    """Extract only the newly written content from the tool input."""
    if "content" in tool_input:
        return tool_input["content"]
    if "new_string" in tool_input:
        return tool_input["new_string"]
    return None


def read_file_safe(path: str, max_bytes: int = 2 * 1024 * 1024) -> str | None:
    """Read the file post-edit so we catch secrets that exist in lines the
    Edit didn't touch (a multi-step Edit can move a secret to a line that
    is never the active new_string). Cap at 2MB; large generated files
    don't need scanning. Returns None on error."""
    try:
        import os
        if os.path.getsize(path) > max_bytes:
            return None
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except (OSError, ValueError):
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

    # Narrow the .claude/ exemption to projects/ only. A blanket exemption
    # for everything under ~/.claude/ would skip skill prompts, hook scripts,
    # and settings.json — meaning a session told to "update the kickoff skill
    # to use a new API key" would write the key without warning. Only the
    # session JSONLs and memory files under projects/ are exempt.
    if "/.claude/projects/" in file_path:
        return  # session JSONLs and memory files legitimately may not be secret-scannable
    if file_path.endswith(".env.example"):
        return
    if not has_scan_extension(file_path):
        return

    # Scanning only new_string misses secrets that already existed in the file
    # on lines the Edit didn't touch. Prefer the full post-edit file; fall back
    # to new_string only if the file isn't readable (e.g., Write to a path
    # that's gone, or the test harness running synthetic input).
    full_content = read_file_safe(file_path)
    diff_content = get_new_content(tool_input)
    content = full_content if full_content is not None else diff_content
    if not content:
        return

    findings = scan_text(content)
    if not findings:
        return

    has_critical = any(critical for _, _, _, critical in findings)

    lines = []
    if has_critical:
        lines.append("!! CRITICAL: Potential hardcoded secrets detected !!")
        lines.append("")

    lines.append(f"Secret patterns found in {file_path} (new content):")
    for line_num, text, label, critical in findings:
        prefix = "CRITICAL" if critical else "WARNING"
        display = text.strip()
        if len(display) > 120:
            display = display[:120] + "..."
        lines.append(f"  [{prefix} - {label}]: {display}")

    lines.append("")
    if has_critical:
        lines.append("STOP: Do not commit this file. Remove or externalize these secrets immediately.")
    else:
        lines.append("Review these lines. If real credentials, move them to environment variables.")

    # Claude Code requires the wrapped hookSpecificOutput envelope; a flat
    # top-level additionalContext is silently discarded.
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": "\n".join(lines),
        }
    }
    json.dump(output, sys.stdout)


if __name__ == "__main__":
    main()
