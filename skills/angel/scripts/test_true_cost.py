#!/usr/bin/env python3
# pattern: imperative shell
"""Regression suite for true-cost.py's per-request collapse.

The bug this pins: the harness can write one transcript record per content
block of an assistant message, each repeating the same `usage` object, so
summing per line multiply-counts a single billed API call. The duplicated
cache classes can make cache writes look anomalous against genuinely new
content.

Run: scripts/test_true_cost.py
"""
import importlib.util
import json
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "true_cost", Path(__file__).resolve().parent / "true-cost.py")
tc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tc)

PASS = FAIL = 0


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


def line(req, *, create=0, read=0, out=0, inp=0, model="claude-sonnet-5", msgid=None):
    """One transcript record. Every record of a request repeats the same usage."""
    d = {"type": "assistant", "message": {
        "id": msgid or f"msg_{req}", "model": model,
        "usage": {"input_tokens": inp, "cache_creation_input_tokens": create,
                  "cache_read_input_tokens": read, "output_tokens": out}}}
    if req is not None:
        d["requestId"] = req
    return json.dumps(d)


# --- 1. the core collapse ---------------------------------------------------
# Two API requests. The first is split over 3 content blocks, the second over 2.
# Non-terminal duplicates carry ~2 output tokens; cache counters repeat in full.
lines = [
    line("req_A", create=10_000, read=0, out=2),
    line("req_A", create=10_000, read=0, out=2),
    line("req_A", create=10_000, read=0, out=500),
    line("req_B", create=1_000, read=10_000, out=2),
    line("req_B", create=1_000, read=10_000, out=300),
]
bm, n = tc.tally_transcript(lines)
c = bm["claude-sonnet-5"]
check(n == 2, "collapses 5 records to 2 API requests", f"got {n}")
check(c["cache_write"] == 11_000, "cache_write counted once per request",
      f"got {c['cache_write']} want 11000")
check(c["cache_read"] == 10_000, "cache_read counted once per request",
      f"got {c['cache_read']} want 10000")
check(c["output"] == 800, "output takes the terminal record, not the sum",
      f"got {c['output']} want 800")
check(list(bm) == ["claude-sonnet-5"], "model preserved", f"got {list(bm)}")

# The naive per-line sum is what shipped first; pin the gap so a regression to
# it is loud rather than a silently larger invoice.
naive_write = sum(json.loads(x)["message"]["usage"]["cache_creation_input_tokens"]
                  for x in lines)
check(naive_write == 32_000 and c["cache_write"] == 11_000,
      "per-line sum would have inflated cache_write 2.9x",
      f"naive {naive_write} vs collapsed {c['cache_write']}")

# --- 2. aborted turns -------------------------------------------------------
# A trailing all-zero record can follow a real request. Selecting the LAST
# record would zero it out; selecting max-output keeps the real one.
lines = [
    line("req_C", create=2_278, read=127_016, out=3),
    line("req_C", create=2_278, read=127_016, out=3),
    line("req_C", create=0, read=0, out=0),
]
bm, n = tc.tally_transcript(lines)
c = bm["claude-sonnet-5"]
check(n == 1, "aborted trailing record does not open a new request", f"got {n}")
check(c["cache_write"] == 2_278 and c["cache_read"] == 127_016,
      "trailing all-zero record does not zero out a real request", str(c))

# --- 3. identity keys -------------------------------------------------------
# requestId can be absent; message.id provides the fallback identity.
lines = [
    line(None, create=100, out=2, msgid="msg_X"),
    line(None, create=100, out=9, msgid="msg_X"),
]
bm, n = tc.tally_transcript(lines)
c = bm["claude-sonnet-5"]
check(n == 1 and c["cache_write"] == 100,
      "falls back to message.id when requestId is absent", f"n={n} {c}")

# With neither key, records must stay distinct rather than collapsing onto a
# shared None -- under-counting is as wrong as over-counting.
lines = [
    json.dumps({"message": {"model": "claude-sonnet-5", "usage": {
        "input_tokens": 0, "cache_creation_input_tokens": 50,
        "cache_read_input_tokens": 0, "output_tokens": 5}}}),
    json.dumps({"message": {"model": "claude-sonnet-5", "usage": {
        "input_tokens": 0, "cache_creation_input_tokens": 70,
        "cache_read_input_tokens": 0, "output_tokens": 5}}}),
]
bm, n = tc.tally_transcript(lines)
c = bm["claude-sonnet-5"]
check(n == 2 and c["cache_write"] == 120,
      "id-less records stay distinct instead of collapsing to one", f"n={n} {c}")

# --- 4. junk tolerance ------------------------------------------------------
bm, n = tc.tally_transcript(
    ["not json", "", json.dumps({"message": "a string"}),
     json.dumps({"message": {"usage": None}}), line("req_D", create=7, out=1)])
c = bm["claude-sonnet-5"]
check(n == 1 and c["cache_write"] == 7, "skips malformed and usage-less lines",
      f"n={n} {c}")

# --- 4b. a transcript is not one model --------------------------------------
# A transcript may contain requests served by different models. Pricing the whole
# file at its first model applies the wrong rate to later requests.
lines = [
    line("req_E", create=1_000, out=10, model="claude-fable-5"),
    line("req_F", create=2_000, out=20, model="claude-opus-5"),
    line("req_G", create=4_000, out=30, model="claude-opus-5"),
]
bm, n = tc.tally_transcript(lines)
check(n == 3 and set(bm) == {"claude-fable-5", "claude-opus-5"},
      "splits counts by the model that served each request", f"n={n} {list(bm)}")
check(bm["claude-fable-5"]["cache_write"] == 1_000
      and bm["claude-opus-5"]["cache_write"] == 6_000,
      "each model carries only its own tokens", str(bm))
# Fable input is 10.0/Mtok vs Opus 5.0 -- pricing the lot as Fable would be 2x.
split = sum(tc.cost_of(c, m)[0] for m, c in bm.items())
allfable, _ = tc.cost_of({"input": 0, "output": 60, "cache_write": 7_000,
                          "cache_read": 0}, "claude-fable-5")
check(split < allfable, "mixed transcript is not priced at its first model",
      f"split {split} vs first-model {allfable}")

# `<synthetic>` is the harness placeholder on an aborted turn: no real model,
# all-zero usage. Counting it adds a bogus roster row and a spurious
# unpriced-model warning.
lines = [
    line("req_H", create=500, out=5),
    json.dumps({"requestId": "req_I", "message": {
        "id": "msg_I", "model": "<synthetic>", "usage": {
            "input_tokens": 0, "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0, "output_tokens": 0}}}),
]
bm, n = tc.tally_transcript(lines)
check(n == 1 and "<synthetic>" not in bm,
      "synthetic aborted-turn records are skipped", f"n={n} {list(bm)}")

# --- 4c. write breakdown ----------------------------------------------------
# write_breakdown consumes COLLAPSED records, so --breakdown costs no re-read.
# Build them through collapse_requests, which is also what main() does — that
# way these tests exercise the real path rather than a hand-built shape.
def tline(req, ts, *, create=0, read=0, out=0, inp=0):
    d = json.loads(line(req, create=create, read=read, out=out, inp=inp))
    d["timestamp"] = ts
    return json.dumps(d)


def collapsed(lines):
    recs, _ = tc.collapse_requests(lines)
    return recs


# A clean 3-turn pass: 10k prefix, then each turn reads all of the previous
# context and writes only what is new. Nothing is ever paid for twice.
clean = [
    tline("r1", "2026-08-09T00:00:00Z", create=10_000, read=0, out=100),
    tline("r2", "2026-08-09T00:00:10Z", create=500, read=10_000, out=100),
    tline("r3", "2026-08-09T00:00:20Z", create=500, read=10_500, out=100),
]
b = tc.write_breakdown([collapsed(clean)])
check(b["first"] == 10_000 and b["rewrite"] == 0 and b["new"] == 1_000,
      "clean pass: all writes are prefix + new content", str(b))
check(b["amplification"] == 1.0, "clean pass amplifies at 1.0x",
      f"got {b['amplification']}")
check(b["turns"] == 2 and b["requests"] == 3 and b["transcripts"] == 1,
      "turns excludes each transcript's first request", str(b))
check(b["rewrite_turns"] == 0, "clean pass has no re-write turns", str(b))

# Same pass, except turn 3's cache went away: it re-reads nothing and re-writes
# the whole 11,000-token context. 10,500 of that is content already paid for.
lost = [
    tline("r1", "2026-08-09T00:00:00Z", create=10_000, read=0, out=100),
    tline("r2", "2026-08-09T00:00:10Z", create=500, read=10_000, out=100),
    tline("r3", "2026-08-09T00:07:00Z", create=11_000, read=0, out=100),
]
b = tc.write_breakdown([collapsed(lost)])
check(b["rewrite"] == 10_500, "expired cache is charged as re-write, not new",
      f"got {b['rewrite']} want 10500")
check(b["rewrite_by_gap"][">=600s"] == 0 and b["rewrite_by_gap"]["300-600s"] == 10_500,
      "re-write is bucketed by the gap that preceded it",
      str(b["rewrite_by_gap"]))
check(b["amplification"] > 1.0, "re-writes push amplification above 1.0",
      f"got {b['amplification']}")
check(b["rewrite_turns"] == 1 and b["turns"] == 2, "rewrite_turns counts the turn",
      str(b))

# --- 4d. context SHRINK is not a re-write -----------------------------------
# Booking context shrink as re-write can drive `new` negative. Turn 3's context
# is smaller than turn 2's—history was dropped,
# not re-written — so it must contribute 0 re-write, not the 9,500 delta.
shrink = [
    tline("r1", "2026-08-09T00:00:00Z", create=10_000, read=0, out=100),
    tline("r2", "2026-08-09T00:00:10Z", create=500, read=10_000, out=100),
    tline("r3", "2026-08-09T00:00:20Z", create=200, read=800, out=100),
]
b = tc.write_breakdown([collapsed(shrink)])
# The vanished 9,500 tokens must NOT be charged. What remains chargeable is at
# most the 200 this turn actually wrote: with the context shrinking there is no
# growth, so tokens written are content that already existed and was not served
# from cache. The unbounded formula charged 9,700 — the whole disappearance.
check(b["rewrite"] == 200,
      "shrink delta is not charged; only the turn's own write can be",
      f"got {b['rewrite']} — unbounded would say 9,700")
check(b["rewrite"] <= 200, "re-write never exceeds the turn's cache_creation",
      f"got {b['rewrite']}")
check(b["new"] >= 0 and b["coherent"],
      "shrink cannot drive `new` negative", str(b))
check(b["shrink_turns"] == 1, "shrink turns are counted and surfaced", str(b))

# re-write can never exceed what the turn actually wrote
for case in (clean, lost, shrink):
    bb = tc.write_breakdown([collapsed(case)])
    check(bb["rewrite"] <= bb["write"] and bb["new"] >= 0,
          "re-write is bounded by actual writes in every case", str(bb))

# --- 4e. multi-transcript isolation -----------------------------------------
# main()'s real call site is multi-transcript. Hoisting peak/prev_ctx out of the
# per-transcript loop leaks state across unrelated agents and yields a negative
# `new` — a mutation none of the single-transcript assertions above can catch.
b = tc.write_breakdown([collapsed(clean), collapsed(lost)])
one = tc.write_breakdown([collapsed(clean)])
two = tc.write_breakdown([collapsed(lost)])
check(b["transcripts"] == 2 and b["requests"] == 6, "counts both transcripts", str(b))
for k in ("first", "rewrite", "new", "write"):
    check(b[k] == one[k] + two[k],
          f"multi-transcript `{k}` is the sum of the parts, with no cross-leak",
          f"{b[k]} != {one[k]} + {two[k]}")
check(b["peak"] == one["peak"] + two["peak"],
      "peak context does not leak between transcripts", str(b))
check(b["coherent"], "multi-transcript decomposition stays coherent", str(b))

# --- 4f. missing timestamps get their own bucket ----------------------------
# Without an `unknown` bucket the gap percentages silently sum below 100%.
no_ts = [
    line("r1", create=10_000, read=0, out=100),
    line("r2", create=11_000, read=0, out=100),
]
b = tc.write_breakdown([collapsed(no_ts)])
check(b["rewrite"] > 0 and b["rewrite_by_gap"]["unknown"] == b["rewrite"],
      "re-write with no timestamps lands in the `unknown` bucket",
      str(b["rewrite_by_gap"]))
check(sum(b["rewrite_by_gap"].values()) == b["rewrite"],
      "gap buckets always sum to the full re-write mass",
      str(b["rewrite_by_gap"]))

# --- 4g. the collapse anomaly counter ---------------------------------------
# Duplicate records that DISAGREE on cache counters mean the harness changed.
agree = [line("r1", create=100, read=5, out=2), line("r1", create=100, read=5, out=9)]
_, an = tc.collapse_requests(agree)
check(an == 0, "identical duplicates are not an anomaly", f"got {an}")

disagree = [line("r1", create=100, read=5, out=2), line("r1", create=777, read=5, out=9)]
_, an = tc.collapse_requests(disagree)
check(an == 1, "disagreeing duplicates are counted", f"got {an}")

# the known-benign case: a trailing all-zero abort must NOT count as anomalous
abort = [line("r1", create=2_278, read=127_016, out=3), line("r1")]
recs, an = tc.collapse_requests(abort)
check(an == 0 and recs[0]["cr"] == 2_278,
      "a trailing all-zero abort is benign, not a counter disagreement",
      f"an={an} {recs}")

# --- 5. pricing is unchanged by the fix -------------------------------------
usd, guessed = tc.cost_of(
    {"input": 0, "output": 1_000_000, "cache_write": 0, "cache_read": 0},
    "claude-sonnet-5")
check(abs(usd - 15.0) < 1e-9 and not guessed, "output priced at list",
      f"got {usd}")
usd, _ = tc.cost_of(
    {"input": 0, "output": 0, "cache_write": 1_000_000, "cache_read": 0},
    "claude-sonnet-5")
check(abs(usd - 3.75) < 1e-9, "cache write bills at 1.25x input (5m TTL)",
      f"got {usd}")
usd, guessed = tc.cost_of(
    {"input": 1_000_000, "output": 0, "cache_write": 0, "cache_read": 0},
    "claude-nonexistent-9")
check(guessed, "unknown model flags a guessed price", f"guessed={guessed}")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
