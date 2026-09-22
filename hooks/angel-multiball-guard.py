#!/usr/bin/env python3
"""PreToolUse hook (Skill, Agent): enforce that /angel runs MULTIBALL (N>=2).

A requested multi-pass review must not silently become a single pass. Independent
later passes materially improve recall and have added new correctness, evidence,
chronology, and ownership checks. Resource tradeoffs must be surfaced to the user
rather than silently resolved by reducing the pass count, so this hook binds the
invariant at the tool boundary.

Two enforcement points:
- Skill(angel) carrying a single-pass flag (--single / --no-multiball /
  --multiball=1 / --balls 1): HARD DENY. Clean, no false positives.
- Agent dispatch that hand-rolls an angel persona (prompt references
  skills/angel/personas/): inject a decision-point REMINDER (debounced ~10min so
  a legit N>=2 run doesn't spam it). A hook can't count passes across separate
  Agent calls, so the hand-rolled path is nudged, not blocked -- the durable fix
  there is "route /angel through the Skill tool."
"""

from __future__ import annotations

import json
import os
import re
import sys
import time

# Single-pass flags, tolerant of `=`/space and surrounding whitespace.
SINGLE_FLAGS = re.compile(r"(?:^|\s)(--single|--no-multiball)(?:\s|$)")
BALLS_ONE = re.compile(
    r"(?:^|\s)(--multiball[=\s]+1|--balls[=\s]+1)(?:\s|$)"
)

DEBOUNCE_FILE = "/tmp/.angel-multiball-reminder"
DEBOUNCE_SEC = 600

# Reinforce the requested multi-pass invariant at hand-rolled dispatch points.
REMINDER = """[angel multiball guard] Hand-rolled angel battery detected. Dispatch EACH persona >=2 independent times (N=2; N=3 on --full/--all).

Independent later passes materially improve recall and have added new correctness, evidence, chronology, and ownership checks. Cross-persona breadth does not replace repeated sampling within a persona.

Do not silently turn a requested multi-pass review into one pass based on target size, focus, or lane count. If the resource cost is material, surface the tradeoff and let the user choose rather than quietly reducing N. Prefer routing /angel through the Skill tool when the scope fits."""


def deny(reason: str) -> int:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        },
        sys.stdout,
    )
    return 0


def inject(context: str) -> int:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": context,
            }
        },
        sys.stdout,
    )
    return 0


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    tool = data.get("tool_name", "")
    ti = data.get("tool_input", {}) or {}

    if tool == "Skill":
        skill = str(ti.get("skill", ""))
        args = str(ti.get("args", ""))
        is_angel = skill == "angel" or skill.endswith(":angel")
        if is_angel and (SINGLE_FLAGS.search(args) or BALLS_ONE.search(args)):
            return deny(
                "Blocked: /angel must run multiball (N>=2). Independent later "
                "passes materially improve recall and have added new correctness, "
                "evidence, chronology, and ownership checks. Remove "
                "--single/--no-multiball/--multiball=1/--balls 1 and let the skill "
                "default to N=2 (N=3 on --full/--all). If resources are constrained, "
                "surface the tradeoff and let the user decide -- do not silently "
                "turn a requested multi-pass review into one pass."
            )
        return 0

    if tool == "Agent":
        prompt = str(ti.get("prompt", ""))
        if "skills/angel/personas/" in prompt or "/angel/personas/" in prompt:
            now = time.time()
            try:
                last = os.path.getmtime(DEBOUNCE_FILE)
            except OSError:
                last = 0.0
            if now - last > DEBOUNCE_SEC:
                try:
                    with open(DEBOUNCE_FILE, "w"):
                        pass
                except OSError:
                    pass
                return inject(REMINDER)
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
