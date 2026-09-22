#!/usr/bin/env python3
"""PostToolUse hook (Agent): log premium-model subagent dispatches for doctrine
review.

If your CLAUDE.md declares a cost-tier doctrine ("premium model X for these
kinds of dispatches, cheaper models for the rest"), that doctrine has no
observable on its own — a session that hoards the premium model and one that
uses it exactly as intended look identical from the outside. This hook is that
observable: it appends one JSONL line per tagged or premium-model Agent
dispatch so a periodic review can answer "is the tier system actually being
used, or hoarded?"

adapt: PREMIUM_MODEL and TAG_RE are the two things to configure for your own
doctrine — either edit the constants below or set the env vars. The default
premium model is the Agent tool's top-tier alias at the time of writing; the
default tags are [tier-consult]/[tier-overview]/[tier-stint]/[tier-driver].

Categories (the `tier` field):
- consult / overview / stint  -> a DELIBERATE doctrine-tier invocation. Set by
  prefixing the Agent `description` with a tag matching TAG_RE, e.g.
  `[tier-consult]` / `[tier-overview]` (stint is normally a driver-mode
  change, not a subagent — logged only if a marker Agent call carries the
  stint tag).
- untagged-premium -> an explicit premium-model dispatch with no tier tag
  (e.g. a routine subagent pinned to the premium model). The safety net:
  catches deliberate spend even when the tag is forgotten, so the log never
  silently under-counts.

Two known blind spots, by design — read the `model` field, don't trust the
tag alone:
1. Cannot capture DRIVER-level spend: a session running interactively on the
   premium model, with no Agent dispatch at all, is entirely invisible to
   this hook. It only fires on subagent dispatches, so it is a secondary
   detail view, not the primary spend signal — check the usage meter for
   that.
2. The tag does not prove which model ran: a dispatch that inherits the
   session's model (no explicit `model` param) is recorded as
   `model: "(inherited)"`, and a tagged dispatch can still land on a
   different model than requested (quota fallback, a typo, an unpinned
   default). Read the `model` field on each row rather than trusting the tag
   — a stale regex or a model mismatch fails silently, since this hook
   always exits 0.

Never blocks or perturbs the tool call: always exits 0, swallows all errors.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone

# adapt: name of your fleet's premium/expensive model tier, matched
# case-insensitively as a substring of tool_input.model.
PREMIUM_MODEL = os.environ.get("CTX_TIER_PREMIUM_MODEL", "fable")

# adapt: tag vocabulary read from the Agent `description` field. Default
# matches [tier-consult] / [tier-overview] / [tier-stint] / [tier-driver].
TAG_RE = re.compile(
    os.environ.get(
        "CTX_TIER_TAG_RE", r"\[tier-(consult|overview|stint|driver)\]"
    ),
    re.IGNORECASE,
)


def log_path() -> str:
    """Honor HOOK_TEST_STATE_DIR so test-hooks.sh can exercise this hook
    without appending to the real doctrine log. Mirrors the convention in
    gh-identity-guard.py / hook-utils.sh."""
    test_dir = os.environ.get("HOOK_TEST_STATE_DIR")
    if test_dir:
        return os.path.join(test_dir, "model-tier-log.jsonl")
    return os.path.expanduser("~/.claude/state/model-tier-log.jsonl")


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    if data.get("tool_name", "") != "Agent":
        return 0

    ti = data.get("tool_input", {}) or {}
    model = str(ti.get("model") or "").lower()
    desc = str(ti.get("description") or "")

    tag = TAG_RE.search(desc)
    is_premium_model = PREMIUM_MODEL.lower() in model

    # Nothing to log unless a doctrine tag is present or the model is
    # explicitly the premium tier.
    if not (tag or is_premium_model):
        return 0

    if tag:
        tier = tag.group(1).lower()
    else:
        tier = "untagged-premium"

    line = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tier": tier,
        "model": model or "(inherited)",
        "desc": desc[:120],
        "cwd": data.get("cwd") or os.getcwd(),
        "session_id": data.get("session_id", ""),
    }

    path = log_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError:
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
