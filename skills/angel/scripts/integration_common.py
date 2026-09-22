#!/usr/bin/env python3
"""Shared deterministic core for ADR-20 integration scripts."""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

SEVERITIES = ("critical", "important", "minor", "noted")
SEV_RANK = {name: len(SEVERITIES) - i for i, name in enumerate(SEVERITIES)}
EFFORTS = ("trivial", "moderate", "significant")
EVIDENCE = ("cited-spec", "code-site", "inference")
VERDICTS = ("APPROVED", "APPROVED (with suggestions)",
            "CHANGES RECOMMENDED", "CHANGES REQUIRED")
DEGRADED_REASONS = ("reducer-failed-twice", "no-qualified-runner",
                    "sandbox-unavailable", "sandbox-cleanup-failed",
                    "runner-cleanup-failed", "shard-depth-exceeded")
EXCLUSION_REASONS = ("instruction-shaped-content-redacted", "malformed-nonfinding",
                     "non-defect-observation", "explicitly-withdrawn-by-reconciler")


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def atomic_json(path: Path, value) -> None:
    atomic_text(path, json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON {path}: {exc}") from exc


def norm_file(value):
    if not value:
        return None
    value = str(value).strip().replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    return value.lower()


def line_start(value):
    if value is None:
        return None
    match = re.search(r"\d+", str(value))
    return int(match.group()) if match else None


def title_tokens(value):
    return {x for x in re.findall(r"[a-z0-9]+", (value or "").lower())
            if len(x) > 2 and x not in {"the", "and", "that", "this", "with", "from"}}


def title_overlap(left, right):
    a, b = title_tokens(left), title_tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def strict_match_score(raw, candidate, line_window=10, title_floor=0.45,
                       coordinate_less_floor=0.65):
    """Return a confidence score or None. Never force-binds on file alone."""
    rf, cf = norm_file(raw.get("file")), norm_file(candidate.get("file"))
    overlap = title_overlap(raw.get("title"), candidate.get("title"))
    rl, cl = line_start(raw.get("line")), line_start(candidate.get("line"))
    if rf and cf:
        if rf != cf:
            return None
        if overlap < title_floor:
            return None
        if rl is not None and cl is not None and abs(rl - cl) > line_window:
            return None
        distance_bonus = 0.2 if rl is not None and cl is not None else 0.0
        return overlap + distance_bonus
    if not rf and not cf and overlap >= coordinate_less_floor:
        return overlap
    return None


def exact_key(record):
    return (norm_file(record.get("file")), str(record.get("line") or ""),
            re.sub(r"\s+", " ", (record.get("title") or "").strip().lower()))


def estimate_tokens(value):
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return len(raw), (len(raw) + 3) // 4


def append_progress(run_dir: Path, marker: str) -> None:
    import datetime
    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    with (run_dir / "PROGRESS").open("a", encoding="utf-8") as handle:
        handle.write(f"{marker} {stamp}\n")


def normalize_named_reasons(rows, label="status entry", strict=True):
    """Return the canonical ``[{name, reason}]`` status shape.

    Older runners emitted either ``{"persona": "reason"}`` or a bare persona
    name. Read those forms losslessly enough to keep historical runs renderable,
    while making all newly recorded metadata use one explicit schema.
    """
    normalized = []
    for index, row in enumerate(rows or [], 1):
        if isinstance(row, str):
            name = row.strip()
            if not name and strict:
                raise ValueError(f"{label}: expected a non-empty string")
            normalized.append({"name": name or f"unknown entry {index}",
                               "reason": "reason not recorded"})
            continue
        if not isinstance(row, dict):
            if strict:
                raise ValueError(f"{label}: expected an object or non-empty string")
            normalized.append({"name": f"unknown entry {index}",
                               "reason": "reason not recorded"})
            continue
        name = row.get("name") or row.get("persona")
        reason = row.get("reason")
        # Historical ``{"persona-name": "reason"}`` maps are accepted, but a
        # malformed canonical object such as ``{"reason": "x"}`` must not turn
        # the field name itself into a persona called "reason".
        if not name and len(row) == 1 and not ({"name", "persona", "reason"} & row.keys()):
            name, reason = next(iter(row.items()))
        if not isinstance(name, str) or not name.strip():
            if strict:
                raise ValueError(f"{label}: missing non-empty name")
            name = f"unknown entry {index}"
        if not isinstance(reason, str) or not reason.strip():
            if strict:
                raise ValueError(f"{label}: missing non-empty reason for {name.strip()}")
            reason = "reason not recorded"
        normalized.append({"name": name.strip(), "reason": reason.strip()})
    return normalized
