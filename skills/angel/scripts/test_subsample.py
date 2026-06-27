#!/usr/bin/env python3
# pattern: imperative shell (test harness)
"""Unit + integration tests for the subsample-N analyzer and the shared matcher.

Covers:
  - finding_match.py (the shared matcher — its FIRST test coverage; was untested
    while embedded in recurrence-pilot.py).
  - subsample-analyzer.py pure core (clustering + recall math), with hand-verified
    expected values.
  - end-to-end on a synthetic within_persona_runs fixture (no real multiball data
    exists yet — the 2026-06-07 window was aborted before producing any).

Run: scripts/test_subsample.py   (exit 0 = all pass)
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


ss = _load("subsample_analyzer", "subsample-analyzer.py")

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


def close(a, b, name, tol=1e-9):
    check(a is not None and abs(a - b) <= tol, name, f"got {a}, want {b}")


def nf(file, title, sev="important"):
    return fm.normalize_finding({"file": file, "title": title, "severity": sev})


# ---- matcher (finding_match.py) ----
def test_matcher():
    a = nf("a.py:10", "sql injection in query builder")
    b = nf("a.py:99", "sql injection query builder")           # same issue, diff line
    c = nf("other.py", "sql injection in query builder")       # diff file
    d = nf("a.py", "missing auth check on endpoint")           # diff issue, same file
    check(fm.finding_match(a, b, 0.5), "matcher: same file + high title overlap matches")
    check(not fm.finding_match(a, c, 0.5), "matcher: different file does not match")
    check(not fm.finding_match(a, d, 0.5), "matcher: same file but unrelated title does not match")
    # basename match across shifted paths
    e = nf("src/app/a.py", "sql injection query builder")
    check(fm.finding_match(a, e, 0.5), "matcher: basename match across shifted paths")
    # threshold sensitivity: raise threshold above the overlap -> no match
    check(not fm.finding_match(a, d, 0.99), "matcher: high threshold rejects weak overlap")
    # severity normalization + filtering field
    check(nf("x", "y", "BOGUS")["sev"] == "noted", "matcher: unknown severity -> noted")


# ---- analyzer pure core (hand-verified) ----
def test_core():
    # cluster_sets: A in all 3 passes, B in pass 0 only, C in pass 1 only.
    passes = [
        [nf("a.py:10", "sql injection in query builder"),
         nf("b.py", "missing auth check on endpoint")],
        [nf("a.py:11", "sql injection query builder"),
         nf("c.py", "unbounded loop in parser")],
        [nf("a.py", "sql injection in the query builder")],
    ]
    clusters = ss.cluster_pass_sets(passes, 0.5)
    check(len(clusters) == 3, "core: 3 distinct issues clustered", f"got {len(clusters)}")
    sizes = sorted(len(c) for c in clusters)
    check(sizes == [1, 1, 3], "core: cluster pass-presence sizes [1,1,3]", f"got {sizes}")

    # recall(1)=5/9, recall(2)=7/9, recall(3)=1.0 (hand-computed).
    close(ss.recall_at_k(clusters, 3, 1), 5 / 9, "core: recall(1)=5/9")
    close(ss.recall_at_k(clusters, 3, 2), 7 / 9, "core: recall(2)=7/9")
    close(ss.recall_at_k(clusters, 3, 3), 1.0, "core: recall(3)=1.0")
    # reproducibility == recall(1)
    close(ss.reproducibility(clusters, 3), ss.recall_at_k(clusters, 3, 1),
          "core: reproducibility == recall(1)")

    # degenerate: all findings identical across passes -> recall(1)=1.0
    stable = [[nf("t.py", "flaky timing assertion")] for _ in range(3)]
    sc = ss.cluster_pass_sets(stable, 0.5)
    check(len(sc) == 1, "core: identical-across-passes -> 1 cluster", f"got {len(sc)}")
    close(ss.recall_at_k(sc, 3, 1), 1.0, "core: stable persona recall(1)=1.0")

    # empty -> None, no crash
    check(ss.recall_at_k([], 3, 1) is None, "core: empty cluster set -> None")
    check(ss.reproducibility([], 3) is None, "core: empty reproducibility -> None")


# ---- end-to-end via analyze() on a fixture ----
def test_end_to_end():
    wpr = {
        "adv": [
            [{"severity": "critical", "file": "a.py:10", "title": "sql injection in query builder"},
             {"severity": "important", "file": "b.py", "title": "missing auth check on endpoint"},
             {"severity": "noted", "file": "z.py", "title": "consider a comment here"}],
            [{"severity": "critical", "file": "a.py:11", "title": "sql injection query builder"},
             {"severity": "important", "file": "c.py", "title": "unbounded loop in parser"}],
            [{"severity": "critical", "file": "a.py", "title": "sql injection in the query builder"}],
        ],
        "test": [
            [{"severity": "important", "file": "t.py", "title": "flaky timing assertion"}],
            [{"severity": "important", "file": "t.py", "title": "flaky timing assertion here"}],
            [{"severity": "important", "file": "t.py", "title": "flaky timing assertion"}],
        ],
    }
    snaps = [("fixture", wpr)]
    instances, agg, per = ss.analyze(snaps, 0.5, "importantplus")
    check(len(instances) == 2, "e2e: 2 persona instances", f"got {len(instances)}")
    # noted finding filtered: adv has 3 Important+ issues, not 4
    adv = next(i for i in instances if i["persona"] == "adv")
    check(adv["full"] == 3, "e2e: importantplus drops the noted finding (adv full=3)", f"got {adv['full']}")
    # aggregate recall by N=3, weighted by full-set size (adv=3, test=1):
    # k1 = (5/9*3 + 1*1)/4 = 2/3 ; k2 = (7/9*3 + 1*1)/4 = 5/6 ; k3 = 1.0
    rc = agg[3]["recall"]
    close(rc[1], 2 / 3, "e2e: aggregate recall(1)=2/3")
    close(rc[2], 5 / 6, "e2e: aggregate recall(2)=5/6")
    close(rc[3], 1.0, "e2e: aggregate recall(3)=1.0")
    close(per["test"]["reproducibility"], 1.0, "e2e: test persona reproducibility=1.0")
    close(per["adv"]["reproducibility"], 5 / 9, "e2e: adv persona reproducibility=5/9")

    # single-pass persona is skipped (need >=2 passes for a curve)
    snaps2 = [("f2", {"naive": [[{"severity": "important", "file": "n.py", "title": "x y z"}]]})]
    inst2, _, _ = ss.analyze(snaps2, 0.5, "importantplus")
    check(len(inst2) == 0, "e2e: persona with <2 passes is skipped")


test_matcher()
test_core()
test_end_to_end()
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
