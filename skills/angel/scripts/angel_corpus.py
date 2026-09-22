#!/usr/bin/env python3
# pattern: imperative shell
"""Shared corpus access for ~/.angel/runs/ — snapshot discovery, dating, and scoping.

Centralizing `SNAPSHOT_CANDIDATES` and `run_date` keeps consumers from drifting or
dropping the caller-side guard that makes the date sentinel safe (see `in_scope`).
Every consumer imports from here; add a filename variant once, in one place.
"""
import json

# Snapshot filename drift across run history. First parseable file with a
# `findings` list wins. The canonical name (post-2026-05-30) is first.
SNAPSHOT_CANDIDATES = [
    "findings-snapshot.json",
    "integrator-snapshot.json",
    "snapshot.json",
    "integrator-output.json",
]

# Returned by run_date() when a run carries no `date` field and its directory name
# does not begin with a YYYYMMDD stem. It deliberately sorts ABOVE every real date
# ('?' is 0x3F, digits are 0x30-0x39), so a bare `date < since` comparison silently
# admits undatable runs instead of excluding them. Never compare it directly —
# use in_scope(), which carries the guard.
UNDATABLE = "????-??-??"


def load_snapshot(run_dir):
    """-> (data, filename, errors)

    `errors` is a list of (path, reason) for candidates that existed but could not be
    read or parsed. Callers must surface it: a corrupted corpus that is silently
    skipped yields a legitimate-looking result on a denominator nobody audited.
    """
    errors = []
    for name in SNAPSHOT_CANDIDATES:
        p = run_dir / name
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text())
        except Exception as exc:
            errors.append((p, f"{type(exc).__name__}: {exc}"))
            continue
        if isinstance(data, dict) and isinstance(data.get("findings"), list):
            return data, name, errors
        errors.append((p, "no `findings` list"))
    return None, None, errors


def run_date(data, run_dir):
    """-> 'YYYY-MM-DD' from the snapshot's own field, else the directory stem, else UNDATABLE."""
    d = (data or {}).get("date")
    if d:
        return d
    stem = run_dir.name[:8]
    if len(stem) == 8 and stem.isdigit():
        return f"{stem[:4]}-{stem[4:6]}-{stem[6:8]}"
    return UNDATABLE


def in_scope(date, since):
    """-> True when `date` is on/after `since`. Undatable runs are OUT of scope.

    This is the guard `run_date`'s sentinel requires. Excluding unknown-date runs is
    the conservative direction: including them would let a run of unknown vintage into
    a window it may predate, and for a pre-registered falsifier that biases toward firing.
    """
    if not since:
        return date != UNDATABLE
    if date == UNDATABLE:
        return False
    return date >= since
