#!/usr/bin/env python3
# pattern: imperative shell (test harness)
"""Unit tests for persona-overlap.py — the cross-persona overlap analyzer.

Covers the pure core (issue_match, dedup_pool, snapshot_overlap) with
hand-verified expected values, plus build_pools canonicalization and analyze()
aggregation on a small fixture.

Run: scripts/test_persona_overlap.py   (exit 0 = all pass)
"""
import importlib.util
import sys
from pathlib import Path

DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(DIR))

import finding_match as fm  # noqa: E402


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, DIR / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


po = _load("persona_overlap", "persona-overlap.py")

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


def nf(file, title, sev="important", line=None):
    return fm.normalize_finding({"file": file, "title": title, "severity": sev, "line": line})


# ---- extract_line: explicit field (int / str / range) or ':NNN' suffix ----
def test_extract_line():
    check(fm.extract_line({"line": 206}) == 206, "extract_line: int field")
    check(fm.extract_line({"line": "206"}) == 206, "extract_line: str field")
    check(fm.extract_line({"line": "188-192"}) == 188, "extract_line: range -> start")
    check(fm.extract_line({"file": "a.py:311"}) == 311, "extract_line: ':NNN' file suffix")
    check(fm.extract_line({"file": "a.py", "line": None}) is None, "extract_line: none present -> None")
    check(fm.extract_line({"line": True}) is None, "extract_line: bool is not a line number")


# ---- file-line mode: same file + (near-line OR title), an interior point ----
def test_file_line_mode():
    # Same file, DISJOINT titles, near lines -> file-title misses, file-line catches.
    a = nf("m.py", "unvalidated input reaches sink", line=100)
    b = nf("m.py", "missing parameterization guard", line=104)  # 4 lines away, no title overlap
    check(not po.issue_match(a, b, 0.5, False, "file-title"), "file-line: disjoint titles miss under file-title")
    check(po.issue_match(a, b, 0.5, False, "file-line", line_window=10), "file-line: near lines match under file-line")
    check(not po.issue_match(a, b, 0.5, False, "file-line", line_window=2), "file-line: outside window falls back to (failing) title")
    # Far apart lines, disjoint titles -> file-line does NOT match (unlike file-only).
    c = nf("m.py", "dead code block", line=900)
    check(not po.issue_match(a, c, 0.5, False, "file-line", line_window=10), "file-line: far lines + disjoint titles no match")
    check(po.issue_match(a, c, 0.5, False, "file"), "file-line: ...but file-only (upper bound) DOES match same file")
    # Missing line on one side -> file-line falls back to title (here similar -> match).
    d = nf("m.py", "unvalidated input reaches sink now", line=None)
    check(po.issue_match(a, d, 0.5, False, "file-line"), "file-line: missing line falls back to title overlap")


# ---- issue_match: file+title strict, null-file gated behind title_fallback ----
def test_issue_match():
    a = nf("a.py:10", "sql injection in query builder")
    b = nf("a.py:99", "sql injection query builder")
    c = nf("other.py", "sql injection in query builder")
    check(po.issue_match(a, b, 0.5, False), "issue_match: same file + high overlap matches")
    check(not po.issue_match(a, c, 0.5, False), "issue_match: different file no match")
    # null-file findings (absence): unmatchable strict, matchable under fallback
    n1 = nf(None, "no rollback on partial migration failure")
    n2 = nf("", "missing rollback on partial migration failure")
    check(not po.issue_match(n1, n2, 0.5, False), "issue_match: null-file no match when fallback off")
    check(po.issue_match(n1, n2, 0.5, True), "issue_match: null-file matches by title when fallback on")
    # null-file with unrelated title stays unmatched even under fallback
    n3 = nf(None, "unbounded recursion in parser")
    check(not po.issue_match(n1, n3, 0.5, True), "issue_match: null-file unrelated title no match under fallback")


# ---- dedup_pool: within-persona union, null-file collapses by title ----
def test_dedup_pool():
    findings = [
        nf("a.py:10", "sql injection in query builder"),
        nf("a.py:20", "sql injection query builder"),        # dup of #1 (same issue)
        nf("b.py", "missing auth check"),                     # distinct
        nf(None, "no rollback on migration failure"),
        nf(None, "missing rollback on migration failure"),    # dup of #4 by title (within-persona)
    ]
    pool = po.dedup_pool(findings, 0.5)
    check(len(pool) == 3, "dedup_pool: 5 raw -> 3 distinct issues", f"got {len(pool)}")


# ---- snapshot_overlap: hand-verified unique + matched counts ----
def test_snapshot_overlap():
    pools = {
        "A": [nf("a.py:10", "sql injection query"), nf("b.py", "missing auth check")],
        "B": [nf("a.py:99", "sql injection in query"), nf("c.py", "unbounded loop")],
        "C": [nf("d.py", "hardcoded secret token")],
    }
    so = po.snapshot_overlap(pools, 0.5, False)
    check(so["sizes"] == {"A": 2, "B": 2, "C": 1}, "overlap: pool sizes", f"got {so['sizes']}")
    check(so["unique"] == {"A": 1, "B": 1, "C": 1}, "overlap: unique counts", f"got {so['unique']}")
    check(so["matched"].get(("A", "B")) == 1, "overlap: A->B matched=1 (sql injection)", f"got {so['matched']}")
    check(so["matched"].get(("B", "A")) == 1, "overlap: B->A matched=1", f"got {so['matched']}")
    check(so["matched"].get(("A", "C"), 0) == 0, "overlap: A->C matched=0")
    check(so["nullfile"] == {"A": 0, "B": 0, "C": 0}, "overlap: no null-file findings here")


# ---- build_pools: canonicalizes persona keys, needs >=2 passes ----
def test_build_pools():
    amap = {"hypercritical": "hyper", "hyper": "hyper"}
    wpr = {
        "hyper": [[{"severity": "critical", "file": "a.py", "title": "sql injection here"}],
                  [{"severity": "critical", "file": "a.py", "title": "sql injection here"}]],
        "hypercritical": [[{"severity": "important", "file": "b.py", "title": "missing auth guard"}],
                          [{"severity": "important", "file": "b.py", "title": "missing auth guard"}]],
        "naive": [[{"severity": "noted", "file": "z.py", "title": "style nit"}],
                  [{"severity": "noted", "file": "z.py", "title": "style nit"}]],
    }
    pools = po.build_pools(wpr, 0.5, "importantplus", amap)
    # hyper + hypercritical merge -> one 'hyper' pool with 2 distinct issues;
    # naive drops entirely (only a noted finding, filtered by importantplus).
    check("hyper" in pools and "hypercritical" not in pools, "build_pools: canonicalizes hyper/hypercritical")
    check(len(pools.get("hyper", [])) == 2, "build_pools: merged hyper pool has 2 issues", f"got {pools.get('hyper')}")
    check("naive" not in pools, "build_pools: importantplus drops noted-only persona")
    # single-pass persona is excluded (need >=2 passes to call a union a pool)
    wpr1 = {"adv": [[{"severity": "critical", "file": "a.py", "title": "x y z"}]]}
    check(po.build_pools(wpr1, 0.5, "importantplus", amap) == {}, "build_pools: <2 passes excluded")


# ---- analyze: aggregation across snapshots + a clean merge-candidate pair ----
def test_analyze():
    # Two personas that find the SAME issue in both of two snapshots -> mutual
    # overlap 1.0, unique 0; a third persona always solo -> unique 1.0.
    # canon_persona lowercases, so use canonical-lowercase keys in the fixture.
    def snap(issue_file, issue_title):
        return ("s", {
            "twina": [[{"severity": "critical", "file": issue_file, "title": issue_title}],
                      [{"severity": "critical", "file": issue_file, "title": issue_title}]],
            "twinb": [[{"severity": "critical", "file": issue_file, "title": issue_title}],
                      [{"severity": "critical", "file": issue_file, "title": issue_title}]],
            "loner": [[{"severity": "critical", "file": "solo.py", "title": "unique bug " + issue_title}],
                      [{"severity": "critical", "file": "solo.py", "title": "unique bug " + issue_title}]],
        })
    snaps = [snap("a.py", "sql injection here"), snap("b.py", "path traversal there")]
    per, pairs, cov = po.analyze(snaps, 0.5, "importantplus", False, {})
    check(per["twina"]["unique_rate"] == 0.0, "analyze: twina fully corroborated (unique=0)", f"got {per['twina']}")
    check(per["loner"]["unique_rate"] == 1.0, "analyze: loner fully unique", f"got {per['loner']}")
    twin_pair = next((p for p in pairs if {p["a"], p["b"]} == {"twina", "twinb"}), None)
    check(twin_pair is not None and twin_pair["merge_score"] == 1.0,
          "analyze: twina/twinb are a merge candidate (merge_score=1.0)", f"got {twin_pair}")
    check(twin_pair["cooccur"] == 2, "analyze: twin pair co-occurs in 2 snapshots", f"got {twin_pair}")
    check(cov["personas"] == 3, "analyze: 3 canonical personas", f"got {cov}")


test_extract_line()
test_file_line_mode()
test_issue_match()
test_dedup_pool()
test_snapshot_overlap()
test_build_pools()
test_analyze()
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
