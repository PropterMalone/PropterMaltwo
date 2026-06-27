#!/usr/bin/env python3
# pattern: functional core
"""Canonicalize persona keys across run history — shared by mine-runs.py and
recurrence-pilot.py (extracted 2026-06-12; the two copies had already diverged).

Personas log under inconsistent keys: the file stem (`adversarial`,
`thousand-foot`, `future-me`) and the short frontmatter name (`adv`,
`thousand`, `future`) both appear, which fragments per-persona stats into
duplicate rows. The alias map is derived from personas/*.md so a renamed/added
persona needs no edit here.
"""
from pathlib import Path


def _frontmatter_name(path):
    """The canonical short key a persona logs under is its frontmatter `name:`."""
    try:
        lines = path.read_text().splitlines()
    except Exception:
        return None
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.strip().startswith("name:"):
            return line.split(":", 1)[1].strip().strip("\"'").lower() or None
    return None


def build_persona_aliases(skill_dir):
    """Map persona-file stems AND frontmatter names to the canonical short name.

    Returns {} if the personas dir is absent (callers then fall back to
    case-folding only, i.e. pre-alias behavior).
    """
    amap = {}
    pdir = Path(skill_dir) / "personas"
    if not pdir.is_dir():
        return amap
    for f in pdir.glob("*.md"):
        stem = f.stem.strip().lower()
        canon = _frontmatter_name(f) or stem
        amap[stem] = canon
        amap[canon] = canon
    return amap


def canon_persona(name, amap):
    k = (name or "").strip().lower()
    return amap.get(k, k)
