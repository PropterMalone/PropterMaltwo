#!/usr/bin/env python3
# pattern: imperative shell (test harness)
"""Unit tests for parse-findings.py — the md->struct parser (ADR-12 capture pipeline).

Fixtures are synthetic examples covering three formats plus None and junk.
Run: scripts/test_parse_findings.py   (exit 0 = all pass)
"""
import importlib.util
import sys
from pathlib import Path

DIR = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("parse_findings", DIR / "parse-findings.py")
pf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pf)

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


# ---- Format A: canonical (#### headers, bold title, backtick file:line, None.) ----
FMT_A = """## Naive Review

### Findings

#### Critical (blocks ship)
None.

#### Important (should fix)
None.

#### Minor (quality improvement)

- **Confusing normalizeWidget location** `[moderate]` — `src/entry.ts:765` — The function is called but never defined here.

- **Magic constant exported but local** `[trivial]` — `src/math/adjust.ts:46` — Exported yet used only in-file.

#### Noted (awareness only)
- Pattern markers are comprehensive and consistent
"""


def test_format_a():
    r = pf.parse_findings(FMT_A)
    check(r["status"] == "ok", "A: status ok", r["status"])
    check(len(r["findings"]) == 3, "A: 3 findings (2 minor + 1 noted; None. sections empty)", str(len(r["findings"])))
    f0 = r["findings"][0]
    check(f0["severity"] == "minor", "A: severity from #### header")
    check(f0["title"] == "Confusing normalizeWidget location", "A: bold title extracted", f0["title"])
    check(f0["file"] == "src/entry.ts" and f0["line"] == "765", "A: backtick file:line", f"{f0['file']}:{f0['line']}")
    check(r["findings"][2]["severity"] == "noted" and r["findings"][2]["file"] is None, "A: noted, no file")


# ---- Format B: compact (bare ####, prose bullets, coords in parens, no bold) ----
FMT_B = """## [Adversarial] Review — pass 1
#### Important
- "loadWidgets supplies the sink" contradicts per-adapter model (widget-pipeline.md:49-51 vs sources.ts:75-105): sink must thread through.
- ProviderAlpha two-layer shell breaks one-call-site (provider-alpha.ts:21-79): onCapture threads through.
#### Minor
- Gzip rotation has no in-repo precedent (zero node:zlib in src/).
#### Noted
- payload:unknown loses type safety for refine narrowing.
"""


def test_format_b():
    r = pf.parse_findings(FMT_B)
    check(r["status"] == "ok", "B: status ok", r["status"])
    check(len(r["findings"]) == 4, "B: 4 findings across bare #### sections", str(len(r["findings"])))
    check(r["findings"][0]["severity"] == "important", "B: bare '#### Important' recognized")
    check(r["findings"][0]["file"] == "widget-pipeline.md" and r["findings"][0]["line"] == "49-51",
          "B: file:line from prose parens", f"{r['findings'][0]['file']}:{r['findings'][0]['line']}")
    # 'payload:unknown' must NOT match as a file (no dot-extension)
    check(r["findings"][3]["file"] is None, "B: 'payload:unknown' not mistaken for a file")


# ---- Format C: bare labels (CRITICAL:/no #, all-caps, run-on NOTED:) ----
FMT_C = """## [Thousand-Foot] pass 1
CRITICAL:
- complete:true attests the FETCH but WorkerDelta diffs the FILE (capture.ts:102-115). Disk-full simulation.
IMPORTANT:
- Periodic sweep keys on last-seen PARTIAL — MISSING snapshot invisible.
MINOR:
- reason not derivable from shipped outcome. Add lastError.
NOTED: ProviderBeta natively marks removals; periodic snapshots censor intra-period churn.
"""


def test_format_c():
    r = pf.parse_findings(FMT_C)
    check(r["status"] == "ok", "C: status ok", r["status"])
    check(len(r["findings"]) == 4, "C: 4 findings incl run-on NOTED:", str(len(r["findings"])))
    check(r["findings"][0]["severity"] == "critical", "C: bare 'CRITICAL:' recognized")
    check(r["findings"][0]["file"] == "capture.ts" and r["findings"][0]["line"] == "102-115",
          "C: file:line from prose", f"{r['findings'][0]['file']}:{r['findings'][0]['line']}")
    noted = r["findings"][3]
    check(noted["severity"] == "noted", "C: run-on 'NOTED: text' becomes a noted finding")
    check("ProviderBeta" in noted["title"], "C: run-on text captured as content", noted["title"])


# ---- None / empty / no-structure loudness ----
def test_empty_and_loud():
    all_none = "## X Review\n\n#### Critical (blocks ship)\nNone.\n#### Important\nNone.\n"
    r = pf.parse_findings(all_none)
    check(r["status"] == "empty" and not r["findings"], "empty: all-None -> status empty, 0 findings", r["status"])
    check(pf.parse_findings("")["status"] == "empty", "empty: blank input -> empty")
    check(pf.parse_findings("No findings.")["status"] == "empty", "empty: bare 'No findings.' -> empty")
    # content but NO severity structure -> loud
    junk = "# Pass 2 Summary\n\nThis run consolidated the following observations into report.md.\nSee the main report for details.\n"
    r = pf.parse_findings(junk)
    check(r["status"] == "no-structure", "loud: prose with no severity section -> no-structure", r["status"])


# ---- field-extraction edge cases ----
def test_fields():
    # multi-line continuation folds into the finding
    ml = "#### Critical (blocks ship)\n- **Race in writer** `[significant]` — `a.ts:10` — first line\n  second line of the same finding.\n"
    r = pf.parse_findings(ml)
    check(len(r["findings"]) == 1, "fields: multi-line bullet is one finding", str(len(r["findings"])))
    check(r["findings"][0]["title"] == "Race in writer", "fields: title stops at bold span")
    # range and single line
    r2 = pf.parse_findings("#### Minor\n- issue at `foo/bar.py:12-20` here\n")
    check(r2["findings"][0]["line"] == "12-20", "fields: line range preserved")
    # a bare 'ratio 3:4' must not be read as file:line
    r3 = pf.parse_findings("#### Noted\n- the ratio 3:4 matters but no file here\n")
    check(r3["findings"][0]["file"] is None, "fields: 'ratio 3:4' not a file")


test_format_a()
test_format_b()
test_format_c()
test_empty_and_loud()
test_fields()
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
