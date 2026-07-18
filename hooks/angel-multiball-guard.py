#!/usr/bin/env python3
"""PreToolUse hook (Skill, Agent): enforce that /angel runs MULTIBALL (N>=2).

the user's standing rule (2026-06): never drop /angel to single-pass. Claude
rationalizes single-pass as "cost-sensible for a small/focused diff," it recurs
across projects and contexts, and when challenged Claude capitulates without
fixing the driver. The cost<->recall tradeoff is the user's to make, not Claude's to
silently optimize away: a single pass catches only ~40% of a persona's Important+
findings; the 2nd independent pass is the recall recovery. Memory notes don't
hold this (proven) -- so this hook binds it at the tool boundary instead.

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
                "Blocked: /angel must run multiball (N>=2). the user's standing rule "
                "(2026-06): never drop angel to single-pass -- the cost<->recall "
                "tradeoff is his, not yours to optimize away, and a 2nd pass "
                "reliably finds real bugs the 1st misses. Remove "
                "--single/--no-multiball/--multiball=1/--balls 1 and let the skill "
                "default to N=2 (N=3 on --full/--all). If cost is a real concern, "
                "surface it and let the user decide -- do not silently single-pass."
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
                return inject(
                    "[angel multiball guard] You are hand-rolling the angel battery "
                    "via Agent dispatches. the user's STANDING RULE: this must be "
                    "MULTIBALL -- dispatch EACH persona >=2 independent times (N=2; "
                    "N=3 for full/all reviews). Do NOT single-pass it, even for a "
                    "'small' or 'focused' target -- that is the exact rationalization "
                    "the user has flagged as a recurring failure. Prefer routing /angel "
                    "through the Skill tool when the scope fits."
                )
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
