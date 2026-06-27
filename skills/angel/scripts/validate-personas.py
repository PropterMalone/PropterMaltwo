#!/usr/bin/env python3
# pattern: imperative shell
"""Validate persona-registry consistency — a drift guard for /retro.

Diffs personas/*.md against the SKILL.md §1 mapping table and the unattended.md
Step 3 model table, reporting:
  - orphan files  : personas/X.md with no unattended.md row
  - orphan rows   : a row pointing at personas/X.md that doesn't exist
  - row parity    : a short-name in one table but not the other
  - tier drift    : model tier disagrees between SKILL.md and unattended.md

Also enforces the persona frontmatter contract (DESIGN.md "Persona frontmatter
contract"): required top-level keys (name, default, modes, experimental,
requires.any_of), the full context: block (digest, project_claude_md,
full_bundle, lane), and NO dead keys (prefers: — removed 2026-06-12, nothing
reads it).

Exit nonzero on any drift. (Models are written differently in the two tables —
"Sonnet 4.6" vs "claude-sonnet-4-6" — so comparison is by tier substring.)

Usage: validate-personas.py [--skill-dir DIR]
"""
import argparse
import re
import sys
from pathlib import Path

TIER_RE = re.compile(r"\b(haiku|sonnet|opus|fable)\b", re.I)
SHORT_RE = re.compile(r"[a-z][a-z-]{1,15}")


def parse_rows(md_text, source):
    """Extract (short, second_cell, tier) from model-table rows.

    A model table is one whose header's last cell is exactly "Model" — header
    tracking (rather than per-row tier sniffing) means a row whose model string
    matches no known tier is REPORTED as a problem instead of silently dropped
    (the old TIER_RE filter made an unrecognized model invisible to every
    downstream check). Returns (rows, problems).
    """
    rows, problems = [], []
    in_model_table = False
    for line in md_text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            in_model_table = False
            continue
        cells = [c.strip().strip("`").strip() for c in line.strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells):
            continue  # separator row
        if cells and cells[-1].lower() == "model":
            in_model_table = len(cells) >= 3  # header row opens a model table
            continue
        if not in_model_table or len(cells) < 3:
            continue
        short = cells[0]
        if not SHORT_RE.fullmatch(short):
            problems.append(f"{source}: model-table row has a malformed short name ('{short}')")
            continue
        m = TIER_RE.search(cells[-1])
        if not m:
            problems.append(f"{source}: '{short}' has an unrecognized model string ('{cells[-1]}') — "
                            f"expected a haiku/sonnet/opus/fable tier")
            continue
        rows.append((short, cells[1], m.group(1).lower()))
    return rows, problems


REQUIRED_TOP = ("name", "default", "modes", "experimental", "requires", "context")
REQUIRED_NESTED = ("any_of", "digest", "project_claude_md", "full_bundle", "lane")
FORBIDDEN_KEYS = ("prefers",)


def check_frontmatter(path):
    """Enforce the persona frontmatter contract (DESIGN.md) on one persona file.

    No YAML lib in stdlib, and the frontmatter is flat enough that key-presence
    checks suffice: top-level keys are unindented `key:` lines, nested keys
    (requires.any_of, the context block) are indented `key:` lines. Returns a
    list of problem strings (empty = conformant).
    """
    rel = f"personas/{path.name}"
    lines = path.read_text().splitlines()
    if not lines or lines[0].strip() != "---":
        return [f"{rel}: missing YAML frontmatter"]
    try:
        end = next(i for i, ln in enumerate(lines[1:], 1) if ln.strip() == "---")
    except StopIteration:
        return [f"{rel}: unterminated YAML frontmatter"]
    fm = lines[1:end]
    top = {ln.split(":")[0].strip() for ln in fm if ln and not ln[0].isspace() and ":" in ln}
    nested = {ln.split(":")[0].strip() for ln in fm if ln and ln[0].isspace() and ":" in ln}
    problems = []
    for k in REQUIRED_TOP:
        if k not in top:
            problems.append(f"{rel}: frontmatter missing required key '{k}:'")
    for k in REQUIRED_NESTED:
        if k not in nested:
            problems.append(f"{rel}: frontmatter missing required nested key '{k}:'")
    for k in FORBIDDEN_KEYS:
        if k in top or k in nested:
            problems.append(f"{rel}: frontmatter carries dead key '{k}:' — remove it (nothing reads it; "
                            f"the pii/deanon pairing is prose-enforced in SKILL.md §1/§4)")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill-dir", default=str(Path(__file__).resolve().parent.parent))
    args = ap.parse_args()
    sd = Path(args.skill_dir)

    skill_rows, skill_problems = parse_rows((sd / "SKILL.md").read_text(), "SKILL.md")
    unatt_rows, unatt_problems = parse_rows((sd / "unattended.md").read_text(), "unattended.md")
    files = {p.name for p in (sd / "personas").glob("*.md")}

    skill = {s: tier for s, _full, tier in skill_rows}
    unatt = {s: tier for s, _file, tier in unatt_rows}
    unatt_file = {s: f for s, f, _t in unatt_rows}

    problems = skill_problems + unatt_problems

    for p in sorted((sd / "personas").glob("*.md")):
        problems.extend(check_frontmatter(p))

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
