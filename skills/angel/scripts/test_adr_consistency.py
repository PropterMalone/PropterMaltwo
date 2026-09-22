#!/usr/bin/env python3
# pattern: functional core (status parse + consistency check) / imperative shell (self-tests, CLI)
"""ADR -> SKILL.md consistency gate.

The deciding path is `docs/decisions/*.md`; the ACTING path is SKILL.md (what the
orchestrator actually reads at run time). A shipped ADR can otherwise diverge from
the acting instructions without detection because §3's pre-flight validates persona
frontmatter rather than decision consistency.

This gate closes it: every live (adopted/accepted/active) ADR must be named in
SKILL.md, or carry an explicit entry in ACTING_SURFACE_EXEMPTIONS saying why its
acting surface is somewhere else. It also fails on an unparseable status (an ADR
the gate cannot classify must not be silently invisible) and on a dangling
`ADR-NN` reference in either orchestrator file.

Run: scripts/test_adr_consistency.py   (exit 0 = all pass)
"""
import re
import sys
import tempfile
from pathlib import Path

DIR = Path(__file__).resolve().parent
SKILL_DIR = DIR.parent

# ADRs whose acting surface is genuinely NOT SKILL.md. Each entry is a deliberate,
# reviewed decision -- not a mute button. Keep this list short; the gate reports an
# entry that is no longer needed (or names a nonexistent ADR) as a problem, so it
# cannot quietly rot into a blanket exemption.
ACTING_SURFACE_EXEMPTIONS = {
    "02": "roster membership is expressed as `default:`/`experimental:` values in "
          "personas/*.md frontmatter, which SKILL.md §1.5 reads at run time. There is "
          "no orchestrator instruction for SKILL.md to carry.",
}

# A status is LIVE if the doctrine still governs a run today.
LIVE_PREFIXES = ("active", "accepted", "adopted")
# ...and RETIRED if it does not. `superseded-in-part` is deliberately LIVE: the
# unsuperseded half is still doctrine (ADR-10's measurability enhancements).
RETIRED_PREFIXES = ("superseded", "rejected", "withdrawn", "proposed", "draft")

ADR_FILE_RE = re.compile(r"^(\d{2})-[a-z0-9-]+\.md$")
STATUS_RE = re.compile(r"^\**\s*status\s*\**\s*:\s*\**\s*(.+?)\s*$", re.I)
REFERENCE_RE = re.compile(r"\bADR-(\d{2})\b")


# ---- functional core -------------------------------------------------------

def parse_status(text):
    """Return the raw status string for an ADR body, or None if it declares none.

    Handles both shapes in this repo: YAML frontmatter (`status: active`) and a
    prose header line (`**Status:** Adopted as the default...`, `Status: accepted
    (the user + Claude)`, `Status: **accepted (v3)** -- ...`).
    """
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                break
            m = STATUS_RE.match(line)
            if m:
                return m.group(1)
    # Prose form: the status line sits in the ADR's opening block.
    for line in lines[:25]:
        m = STATUS_RE.match(line.strip())
        if m:
            return m.group(1)
    return None


def classify(status):
    """'live' | 'retired' | 'unknown' from a raw status string."""
    if status is None:
        return "unknown"
    norm = re.sub(r"[*_`]", "", status).strip().lower()
    if norm.startswith("superseded-in-part") or norm.startswith("superseded in part"):
        return "live"
    for p in LIVE_PREFIXES:
        if norm.startswith(p):
            return "live"
    for p in RETIRED_PREFIXES:
        if norm.startswith(p):
            return "retired"
    return "unknown"


def is_mentioned(acting_text, num, stem):
    """True if the acting path names this ADR in any form the repo actually uses."""
    if re.search(rf"\bADR-{num}\b", acting_text):
        return True
    if re.search(rf"decisions/{num}\b", acting_text):
        return True
    return stem in acting_text


def load_adrs(decisions_dir):
    """[(num, stem, status, kind)] sorted by num."""
    out = []
    for path in sorted(Path(decisions_dir).glob("*.md")):
        m = ADR_FILE_RE.match(path.name)
        if not m:
            continue
        text = path.read_text(encoding="utf-8")
        status = parse_status(text)
        out.append((m.group(1), path.stem, status, classify(status)))
    return out


def check_consistency(decisions_dir, acting_paths, exemptions=None):
    """Return (problems, notes). `acting_paths[0]` is the authoritative acting file.

    Every live ADR must be mentioned in the authoritative acting file. The rest of
    `acting_paths` are only scanned for dangling references.
    """
    exemptions = ACTING_SURFACE_EXEMPTIONS if exemptions is None else exemptions
    problems, notes = [], []
    adrs = load_adrs(decisions_dir)
    if not adrs:
        problems.append(f"no ADR files found under {decisions_dir} -- the gate would pass vacuously")
        return problems, notes

    known = {num for num, _stem, _s, _k in adrs}
    skill_text = Path(acting_paths[0]).read_text(encoding="utf-8")

    for num, stem, status, kind in adrs:
        if kind == "unknown":
            problems.append(
                f"ADR-{num} ({stem}): unrecognized status {status!r} -- cannot tell whether it "
                f"governs runs. Add a status of active/accepted/adopted/superseded-*/proposed/"
                f"rejected, or teach classify() the new vocabulary."
            )
            continue
        if kind == "retired":
            continue
        if is_mentioned(skill_text, num, stem):
            continue
        if num in exemptions:
            notes.append(f"ADR-{num} EXEMPT (acting surface is not SKILL.md): {exemptions[num]}")
            continue
        problems.append(
            f"ADR-{num} ({stem}) is status {status!r} but is NEVER mentioned in "
            f"{Path(acting_paths[0]).name}. The ADR is the DECIDING path; "
            f"{Path(acting_paths[0]).name} is the ACTING path -- an adopted decision the "
            f"orchestrator never reads does not happen. Update {Path(acting_paths[0]).name}, "
            f"or add an ACTING_SURFACE_EXEMPTIONS entry naming where it does act."
        )

    for num, reason in sorted(exemptions.items()):
        if num not in known:
            problems.append(f"stale exemption: ADR-{num} has no file under {decisions_dir} ({reason})")
        elif is_mentioned(skill_text, num, dict((n, s) for n, s, _st, _k in adrs)[num]):
            problems.append(
                f"stale exemption: ADR-{num} IS mentioned in {Path(acting_paths[0]).name} now -- "
                f"delete its ACTING_SURFACE_EXEMPTIONS entry so the list stays a short, live one"
            )

    for p in acting_paths:
        text = Path(p).read_text(encoding="utf-8")
        for num in sorted(set(REFERENCE_RE.findall(text))):
            if num not in known:
                problems.append(f"{Path(p).name} references ADR-{num}, which has no file under {decisions_dir}")

    return problems, notes


# ---- self-tests: prove the guard fires -------------------------------------

PASS = 0
FAIL = 0


def ok(name):
    global PASS
    PASS += 1
    print(f"ok   - {name}")


def bad(name, detail=""):
    global FAIL
    FAIL += 1
    print(f"FAIL - {name}\n     {detail}")


def check(cond, name, detail=""):
    ok(name) if cond else bad(name, detail)


def _tree(tmp, adrs, skill_text, unatt_text="# unattended\n"):
    """Build a synthetic skill tree: adrs = {filename: body}."""
    root = Path(tmp)
    dec = root / "docs" / "decisions"
    dec.mkdir(parents=True)
    for name, body in adrs.items():
        (dec / name).write_text(body, encoding="utf-8")
    skill = root / "SKILL.md"
    skill.write_text(skill_text, encoding="utf-8")
    unatt = root / "unattended.md"
    unatt.write_text(unatt_text, encoding="utf-8")
    return dec, [skill, unatt]


FM_ADOPTED = "---\nid: 42-thing\nstatus: adopted\n---\n\n# ADR-42\n"
PROSE_ADOPTED = (
    "# ADR-43 -- Heterogeneous multiball\n\n"
    "**Status:** Adopted as the default for interactive runs, 2026-08-22 (the user).\n"
)
FM_SUPERSEDED = "---\nid: 44-old\nstatus: superseded-by-42\n---\n\n# ADR-44\n"


def test_status_parsing():
    check(classify(parse_status(FM_ADOPTED)) == "live", "status: frontmatter `status: adopted` -> live")
    check(classify(parse_status(PROSE_ADOPTED)) == "live",
          "status: prose `**Status:** Adopted as the default...` -> live")
    check(classify(parse_status(FM_SUPERSEDED)) == "retired", "status: `superseded-by-NN` -> retired")
    check(classify(parse_status("---\nstatus: superseded-in-part\n---\n")) == "live",
          "status: `superseded-in-part` -> live (the unsuperseded half still governs)")
    check(classify(parse_status("---\nstatus: pending-vibes\n---\n")) == "unknown",
          "status: unrecognized vocabulary -> unknown, not silently skipped")
    check(parse_status("# ADR with no status line\n") is None, "status: absent -> None")


def test_negative_case():
    """THE negative case: an adopted ADR absent from SKILL.md must fail the gate."""
    with tempfile.TemporaryDirectory() as tmp:
        dec, acting = _tree(tmp, {"43-hetero-multiball.md": PROSE_ADOPTED},
                            "# angel\n\nNothing here mentions the new doctrine.\n")
        problems, _notes = check_consistency(dec, acting, exemptions={})
        check(len(problems) == 1, "negative: adopted-but-unmentioned ADR yields exactly 1 problem",
              str(problems))
        check(problems and "ADR-43" in problems[0], "negative: the problem NAMES the ADR",
              str(problems))
        check(problems and "43-hetero-multiball" in problems[0],
              "negative: the problem names the ADR file too", str(problems))


def test_positive_case():
    with tempfile.TemporaryDirectory() as tmp:
        dec, acting = _tree(tmp, {"43-hetero-multiball.md": PROSE_ADOPTED},
                            "# angel\n\nMultiball pass 2 routes to codex (ADR-43).\n")
        problems, _ = check_consistency(dec, acting, exemptions={})
        check(not problems, "positive: mentioning `ADR-43` in SKILL.md clears the gate", str(problems))
    with tempfile.TemporaryDirectory() as tmp:
        dec, acting = _tree(tmp, {"43-hetero-multiball.md": PROSE_ADOPTED},
                            "# angel\n\nSee `docs/decisions/43-hetero-multiball.md`.\n")
        problems, _ = check_consistency(dec, acting, exemptions={})
        check(not problems, "positive: a path-form citation also counts as a mention", str(problems))


def test_retired_not_required():
    with tempfile.TemporaryDirectory() as tmp:
        dec, acting = _tree(tmp, {"44-old.md": FM_SUPERSEDED}, "# angel\n\nnothing\n")
        problems, _ = check_consistency(dec, acting, exemptions={})
        check(not problems, "retired: a superseded ADR need not appear in SKILL.md", str(problems))


def test_unknown_status_fails():
    with tempfile.TemporaryDirectory() as tmp:
        dec, acting = _tree(tmp, {"45-weird.md": "---\nstatus: vibes\n---\n"}, "# angel\n")
        problems, _ = check_consistency(dec, acting, exemptions={})
        check(len(problems) == 1 and "unrecognized status" in problems[0],
              "unknown: an unclassifiable status is a loud failure, not a silent skip", str(problems))


def test_exemptions():
    with tempfile.TemporaryDirectory() as tmp:
        dec, acting = _tree(tmp, {"46-frontmatter-only.md": FM_ADOPTED.replace("42-thing", "46-x")},
                            "# angel\n")
        problems, notes = check_consistency(dec, acting, exemptions={"46": "acts in personas/*.md"})
        check(not problems, "exempt: a registered exemption suppresses the failure", str(problems))
        check(any("EXEMPT" in n for n in notes), "exempt: the exemption is printed, not hidden", str(notes))
    with tempfile.TemporaryDirectory() as tmp:
        dec, acting = _tree(tmp, {"46-frontmatter-only.md": FM_ADOPTED.replace("42-thing", "46-x")},
                            "# angel\n\nsee ADR-46\n")
        problems, _ = check_consistency(dec, acting, exemptions={"46": "acts in personas/*.md"})
        check(len(problems) == 1 and "stale exemption" in problems[0],
              "exempt: an exemption for a now-mentioned ADR is reported as stale", str(problems))
    with tempfile.TemporaryDirectory() as tmp:
        dec, acting = _tree(tmp, {"43-hetero-multiball.md": PROSE_ADOPTED}, "# angel\n\nADR-43\n")
        problems, _ = check_consistency(dec, acting, exemptions={"99": "ghost"})
        check(len(problems) == 1 and "stale exemption" in problems[0],
              "exempt: an exemption naming a nonexistent ADR is reported as stale", str(problems))


def test_dangling_reference():
    with tempfile.TemporaryDirectory() as tmp:
        dec, acting = _tree(tmp, {"43-hetero-multiball.md": PROSE_ADOPTED},
                            "# angel\n\nADR-43 and also ADR-97\n")
        problems, _ = check_consistency(dec, acting, exemptions={})
        check(len(problems) == 1 and "ADR-97" in problems[0],
              "dangling: SKILL.md citing a nonexistent ADR is a problem", str(problems))
    with tempfile.TemporaryDirectory() as tmp:
        dec, acting = _tree(tmp, {"43-hetero-multiball.md": PROSE_ADOPTED}, "# angel\n\nADR-43\n",
                            unatt_text="# unattended\n\nper ADR-98\n")
        problems, _ = check_consistency(dec, acting, exemptions={})
        check(len(problems) == 1 and "ADR-98" in problems[0],
              "dangling: unattended.md is scanned for dangling references too", str(problems))


def test_empty_tree_is_not_a_pass():
    with tempfile.TemporaryDirectory() as tmp:
        dec, acting = _tree(tmp, {}, "# angel\n")
        problems, _ = check_consistency(dec, acting, exemptions={})
        check(len(problems) == 1 and "vacuously" in problems[0],
              "guard: zero ADRs found is a failure, not a free pass", str(problems))


def test_real_tree():
    dec = SKILL_DIR / "docs" / "decisions"
    acting = [SKILL_DIR / "SKILL.md", SKILL_DIR / "unattended.md"]
    problems, notes = check_consistency(dec, acting)
    for n in notes:
        print(f"note - {n}")
    check(not problems, f"real tree: every live ADR is reflected in SKILL.md",
          "\n     ".join(problems))


test_status_parsing()
test_negative_case()
test_positive_case()
test_retired_not_required()
test_unknown_status_fails()
test_exemptions()
test_dangling_reference()
test_empty_tree_is_not_a_pass()
test_real_tree()
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
