#!/usr/bin/env python3
# pattern: imperative shell
"""Validate persona-registry consistency — a drift guard for /retro.

Diffs personas/*.md against the SKILL.md §1 mapping table and the unattended.md
Step 3 model table, reporting:
  - orphan files  : personas/X.md with no unattended.md row
  - orphan rows   : a row pointing at personas/X.md that doesn't exist
  - row parity    : a short-name in one table but not the other
  - tier drift    : model tier disagrees between SKILL.md and unattended.md

Exit nonzero on any drift. (Models are written differently in the two tables —
"Sonnet 4.6" vs "claude-sonnet-4-6" — so comparison is by tier substring.)

Usage: validate-personas.py [--skill-dir DIR]
"""
import argparse
import re
import sys
from pathlib import Path

TIER_RE = re.compile(r"\b(haiku|sonnet|opus)\b", re.I)
SHORT_RE = re.compile(r"[a-z][a-z-]{1,15}")


def parse_rows(md_text):
    """Extract (short, second_cell, tier) from model-table rows.

    Filters to rows whose first cell is a short-name token and whose last cell
    names a model tier — this naturally selects the model tables and skips
    headers, separators, and unrelated tables.
    """
    rows = []
    for line in md_text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip().strip("`").strip() for c in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        short = cells[0]
        if not SHORT_RE.fullmatch(short):
            continue
        m = TIER_RE.search(cells[-1])
        if not m:
            continue
        rows.append((short, cells[1], m.group(1).lower()))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill-dir", default=str(Path(__file__).resolve().parent.parent))
    args = ap.parse_args()
    sd = Path(args.skill_dir)

    skill_rows = parse_rows((sd / "SKILL.md").read_text())
    unatt_rows = parse_rows((sd / "unattended.md").read_text())
    files = {p.name for p in (sd / "personas").glob("*.md")}

    skill = {s: tier for s, _full, tier in skill_rows}
    unatt = {s: tier for s, _file, tier in unatt_rows}
    unatt_file = {s: f for s, f, _t in unatt_rows}

    problems = []

    for s in sorted(skill.keys() - unatt.keys()):
        problems.append(f"row parity: '{s}' in SKILL.md but not unattended.md")
    for s in sorted(unatt.keys() - skill.keys()):
        problems.append(f"row parity: '{s}' in unattended.md but not SKILL.md")
    for s in sorted(skill.keys() & unatt.keys()):
        if skill[s] != unatt[s]:
            problems.append(f"tier drift: '{s}' is {skill[s]} in SKILL.md but {unatt[s]} in unattended.md")

    referenced = set()
    for s, f in sorted(unatt_file.items()):
        if not f.endswith(".md"):
            problems.append(f"unattended row '{s}' second cell is not a .md file ('{f}')")
            continue
        referenced.add(f)
        if f not in files:
            problems.append(f"orphan row: '{s}' -> personas/{f} but the file does not exist")
    for f in sorted(files - referenced):
        problems.append(f"orphan file: personas/{f} is not referenced by any unattended.md row")

    summary = (f"{len(files)} persona files, {len(skill)} SKILL rows, "
               f"{len(unatt)} unattended rows")
    if problems:
        print(f"DRIFT ({len(problems)} issue(s)) — {summary}:")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    print(f"clean: {summary} — all consistent")


if __name__ == "__main__":
    main()
