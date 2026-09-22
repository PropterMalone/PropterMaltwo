#!/usr/bin/env python3
# pattern: functional core + imperative shell
"""True-cost meter for transcript token classes.

`usage.json`/`usage.log` Agent totals are peak-context measurements, not
cumulative spend. This script reads the four billable token classes from the
harness transcripts, collapses duplicate records by request identity, and
prices each request using the model that served it.

Per-pass attribution would require a reliable transcript join key, so this
script does not attribute cost per persona. It scopes transcripts by the run's
time window, reports matching coverage, and emits total plus per-model detail.

Usage:
  true-cost.py <run_dir> [--json] [--write]

  --write   merge `cost` into the run's usage.json (does not touch usage.log)

Prices in `PRICES` are public Anthropic list prices in USD per million tokens.
Cache multipliers follow the public billing semantics. Subscription users may
have zero marginal cash spend, so results are list-price comparisons rather
than claims about an invoice or proof derived from private transcripts.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# --- functional core -------------------------------------------------------

PRICES = {  # (input, output) USD per 1M tokens
    "claude-fable-5": (10.0, 50.0),
    "claude-mythos-5": (10.0, 50.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
CACHE_WRITE_MULT = 1.25   # 5-minute TTL
CACHE_READ_MULT = 0.10
UNKNOWN_MODEL_FALLBACK = "claude-sonnet-5"
SYNTHETIC_MODEL = "<synthetic>"  # harness placeholder on aborted turns


def price_for(model):
    """Longest-prefix match so dated snapshots (…-20251001) resolve."""
    if not model:
        return PRICES[UNKNOWN_MODEL_FALLBACK], True
    best = None
    for k in PRICES:
        if model.startswith(k) and (best is None or len(k) > len(best)):
            best = k
    if best:
        return PRICES[best], False
    return PRICES[UNKNOWN_MODEL_FALLBACK], True


def cost_of(counts, model):
    """counts: dict with input/output/cache_write/cache_read. -> USD float."""
    (pin, pout), guessed = price_for(model)
    usd = (counts["input"] * pin
           + counts["output"] * pout
           + counts["cache_write"] * pin * CACHE_WRITE_MULT
           + counts["cache_read"] * pin * CACHE_READ_MULT) / 1_000_000
    return usd, guessed


def tally_transcript(lines):
    """Sum billable token classes over one agent transcript's API requests.

    Returns ({model: counts}, requests).

    A transcript is not necessarily one model. Price each request using its own
    model and ignore the synthetic abort placeholder.

    One API request can occupy multiple transcript lines because the harness
    emits one record per assistant content block and repeats the request usage
    object. Summing lines therefore double-counts token classes. Collapse on
    `requestId`, falling back to `message.id`, and retain the representative
    carrying the greatest output when duplicate records differ because of a
    trailing all-zero abort record.

    Validate the collapsed order independently: each request's cache-read
    context should be consistent with the preceding request's total context.
    Duplicate records with conflicting live cache counters are anomalies and
    must remain visible.
    """
    records, _ = collapse_requests(lines)
    by_model = {}
    for r in records:
        c = by_model.setdefault(r["model"], {"input": 0, "output": 0,
                                             "cache_write": 0, "cache_read": 0,
                                             "requests": 0})
        c["input"] += r["inp"]
        c["output"] += r["out"]
        c["cache_write"] += r["cr"]
        c["cache_read"] += r["rd"]
        c["requests"] += 1
    return by_model, len(records)


def parse_ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def collapse_requests(lines):
    """Collapse a transcript's usage-bearing lines to one record per API request.

    This is the single implementation used by both ordinary totals and
    `--breakdown`; keeping one path prevents request-selection semantics from
    drifting.

    Returns `(records, anomalies)`. `records` is an ordered list of per-request
    dicts: `model`, `inp`, `cr`, `rd`, `out` (token counts for uncached input,
    cache write, cache read, output) and `ts` (a UTC datetime or None).

    `anomalies` counts requests whose duplicate live records disagree on cache
    counters. A nonzero count means the harness-format assumption may be
    eroding, so it is surfaced rather than swallowed.
    """
    by_request = {}
    anomalies = 0
    for i, line in enumerate(lines):
        try:
            d = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        m = d.get("message")
        if not isinstance(m, dict):
            continue
        u = m.get("usage")
        if not isinstance(u, dict):
            continue
        model = m.get("model")
        if model == SYNTHETIC_MODEL:
            continue  # aborted turn; carries all-zero usage and no real model
        rec = {
            "model": model,
            "inp": u.get("input_tokens", 0) or 0,
            "cr": u.get("cache_creation_input_tokens", 0) or 0,
            "rd": u.get("cache_read_input_tokens", 0) or 0,
            "out": u.get("output_tokens", 0) or 0,
            "ts": parse_ts(d.get("timestamp")),
        }
        # `or i` keeps an id-less record as its own request rather than
        # collapsing every such record onto a shared None key.
        key = d.get("requestId") or m.get("id") or i
        prev = by_request.get(key)
        if prev is None:
            by_request[key] = rec
            continue
        live = _has_usage(prev) and _has_usage(rec)
        if live and (prev["cr"], prev["rd"], prev["inp"]) != (rec["cr"], rec["rd"], rec["inp"]):
            anomalies += 1
        if rec["out"] >= prev["out"]:
            by_request[key] = rec
    return list(by_request.values()), anomalies


def _has_usage(r):
    """An all-zero record is an aborted turn, not a counter disagreement."""
    return (r["cr"] or r["rd"] or r["inp"] or r["out"]) != 0


GAP_BUCKETS = ("<60s", "60-300s", "300-600s", ">=600s", "unknown")


def write_breakdown(transcripts):
    """Where the cache-write budget goes. `transcripts` is an iterable of
    already-collapsed record lists (see `collapse_requests`) -- NOT raw lines,
    so `--breakdown` costs no extra disk read.

    Contexts normally grow in an agentic loop, so a token that enters a context
    should be written to cache once and `sum(cache_creation) ~= max(context)`.
    The ratio is the amplification; a healthy incremental cache sits at ~1.0.
    Writes split three ways:

      first-turn  the dispatch prefix -- system prompt, tool schemas, the task.
                  Irreducible per agent. NOTE it counts only what was WRITTEN:
                  when sibling agents dispatch concurrently on a shared prefix,
                  the first writes it and the rest READ it, so this figure can
                  understate the true prefix size.
      re-write    content already paid for that was NOT served from cache this
                  turn. Baseline is `min(context_(N-1), context_N)`, NOT
                  context_(N-1): context can SHRINK between turns, and content
                  that no longer exists cannot have been re-written. Bounding by
                  the current context makes
                  re-write <= this turn's cache_creation by construction, so
                  `new` cannot go negative. On a shrinking turn that leaves at
                  most the turn's own write chargeable: with no growth, tokens
                  written are content that already existed and was not served
                  from cache. The vanished remainder is dropped, not re-written.
      new         everything else: genuinely new content entering the context.

    ORDERING ASSUMPTION: records are taken in transcript order and treated as
    chronological because the gap histogram compares adjacent timestamps.
    Violations are counted in `out_of_order` rather than silently skewing the
    buckets.
    """
    b = {"first": 0, "rewrite": 0, "new": 0, "write": 0, "peak": 0,
         "requests": 0, "transcripts": 0, "rewrite_turns": 0, "turns": 0,
         "out_of_order": 0, "shrink_turns": 0,
         "rewrite_by_gap": {k: 0 for k in GAP_BUCKETS}}
    for rs in transcripts:
        if not rs:
            continue
        b["transcripts"] += 1
        b["requests"] += len(rs)
        peak = prev_ctx = 0
        prev_ts = None
        for i, r in enumerate(rs):
            ctx = r["inp"] + r["rd"] + r["cr"]
            peak = max(peak, ctx)
            b["write"] += r["cr"]
            if i == 0:
                b["first"] += r["cr"]
            else:
                b["turns"] += 1
                if ctx < prev_ctx:
                    b["shrink_turns"] += 1
                # content that no longer exists cannot have been re-written
                rw = min(prev_ctx, ctx) - r["rd"] - r["inp"]
                if rw > 0:
                    b["rewrite"] += rw
                    b["rewrite_turns"] += 1
                    if r["ts"] and prev_ts:
                        if r["ts"] < prev_ts:
                            b["out_of_order"] += 1
                        g = (r["ts"] - prev_ts).total_seconds()
                        k = ("<60s" if g < 60 else "60-300s" if g < 300
                             else "300-600s" if g < 600 else ">=600s")
                    else:
                        k = "unknown"
                    b["rewrite_by_gap"][k] += rw
            prev_ctx, prev_ts = ctx, r["ts"]
        b["peak"] += peak
    b["new"] = b["write"] - b["first"] - b["rewrite"]
    b["amplification"] = round(b["write"] / b["peak"], 2) if b["peak"] else None
    # Per turn, re-write <= that turn's cache_creation, so summed it is <=
    # write - first and `new` is non-negative BY CONSTRUCTION. This flag is
    # therefore unreachable today, and it stays exactly for that reason: it is a
    # canary on the invariant. A negative share is not a coherent measurement.
    b["coherent"] = b["new"] >= 0 and b["rewrite"] >= 0 and b["first"] >= 0
    return b


# --- imperative shell ------------------------------------------------------

def find_transcripts(run_dir, started, ended, projects_root=None):
    """Agent transcripts whose mtime falls in the run window.

    mtime is the completion time, so a pass that started before the window but
    finished inside it is included -- which is what we want for a run total.
    """
    root = Path(projects_root or (Path.home() / ".claude" / "projects"))
    if not root.is_dir():
        return []
    out = []
    for p in root.glob("*/*/subagents/agent-*.jsonl"):
        try:
            mt = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if started and mt < started:
            continue
        if ended and mt > ended:
            continue
        out.append(p)
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", action="store_true",
                    help="merge `cost` into the run's usage.json")
    ap.add_argument("--projects-root", default=None)
    ap.add_argument("--slack-seconds", type=int, default=900,
                    help="widen the window each side; transcripts flush after the pass ends")
    ap.add_argument("--breakdown", action="store_true",
                    help="split the cache-write budget into first-turn prefix, "
                         "re-write, and genuinely-new content")
    args = ap.parse_args()

    run = Path(args.run_dir)
    uj = run / "usage.json"
    if not uj.is_file():
        print(f"ERROR: no usage.json in {run}", file=sys.stderr)
        return 2
    usage = json.loads(uj.read_text())

    started = parse_ts(usage.get("started_at"))
    ended = parse_ts(usage.get("ended_at"))
    if started:
        started = started.fromtimestamp(started.timestamp() - args.slack_seconds, tz=timezone.utc)
    if ended:
        ended = ended.fromtimestamp(ended.timestamp() + args.slack_seconds, tz=timezone.utc)

    files = find_transcripts(run, started, ended, args.projects_root)
    by_model, total = {}, {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0}
    usd_total, guessed_models, turns_total = 0.0, set(), 0
    collapsed, anomalies_total, matched = [], 0, 0

    for f in files:
        try:
            lines = f.read_text(errors="replace").splitlines()
        except OSError:
            continue
        records, anomalies = collapse_requests(lines)
        if not records:
            continue
        matched += 1
        anomalies_total += anomalies
        if args.breakdown:
            collapsed.append(records)  # read once; --breakdown costs no re-read

        per_model = {}
        for r in records:
            c = per_model.setdefault(r["model"], {"input": 0, "output": 0,
                                                  "cache_write": 0,
                                                  "cache_read": 0, "requests": 0})
            c["input"] += r["inp"]
            c["output"] += r["out"]
            c["cache_write"] += r["cr"]
            c["cache_read"] += r["rd"]
            c["requests"] += 1

        for model, c in per_model.items():
            usd, guessed = cost_of(c, model)
            if guessed and model:
                guessed_models.add(model)
            key = model or "unknown"
            slot = by_model.setdefault(key, {"agents": 0, "requests": 0, "usd": 0.0,
                                             **{k: 0 for k in total}})
            # `agents`: transcripts in which this model served at least one
            # request. A mid-pass switch counts once for EACH model it used, so
            # this column can sum above the matched-transcript count -- that is
            # the honest reading. Crediting only a "primary" model, as the first
            # cut did, left the other model showing real dollars against 0
            # agents and 0 requests.
            slot["agents"] += 1
            slot["requests"] += c["requests"]
            slot["usd"] += usd
            usd_total += usd
            for k in total:
                slot[k] += c[k]
                total[k] += c[k]
        turns_total += len(records)

    # The time window is a scope, not an attribution: concurrent work from other
    # sessions lands inside it. Compare against the run's own dispatch count so a
    # divergence is visible instead of silently inflating the total.
    dispatched = 0
    ujl = run / "usage.jsonl"
    if ujl.is_file():
        dispatched = sum(1 for ln in ujl.read_text(errors="replace").splitlines() if ln.strip())

    recorded = (usage.get("totals") or {}).get("total_tokens")
    cum = sum(total.values())
    payload = {
        "usd_total": round(usd_total, 2),
        "tokens_cumulative": cum,
        "tokens_recorded_peak": recorded,
        "understatement_x": round(cum / recorded, 1) if recorded else None,
        # transcripts matched, not the sum of by_model `agents` -- a mixed-model
        # transcript appears under each model it used, so that sum can exceed it.
        "agents_matched": matched,
        "dispatches_logged": dispatched or None,
        "requests": turns_total,
        "collapse_anomalies": anomalies_total,
        "by_class": total,
        "by_model": {k: {**v, "usd": round(v["usd"], 2)} for k, v in by_model.items()},
        "unpriced_models": sorted(guessed_models),
        "method": "time-window scope over subagent transcripts; no per-persona attribution",
    }

    if args.breakdown:
        payload["write_breakdown"] = write_breakdown(collapsed)

    if args.write:
        usage["cost"] = payload
        uj.write_text(json.dumps(usage, indent=2) + "\n")

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    if not payload["agents_matched"]:
        print(f"no subagent transcripts found in the run window for {run.name}")
        print("  (transcripts may be pruned, or the run predates per-agent transcript retention)")
        return 0

    print(f"run {run.name}")
    print(f"  agents matched : {payload['agents_matched']}  "
          f"({turns_total} API requests)")
    if dispatched and payload["agents_matched"] != dispatched:
        d = payload["agents_matched"] - dispatched
        print(f"  ! window caught {abs(d)} {'more' if d > 0 else 'fewer'} transcripts than the "
              f"{dispatched} dispatches this run logged -- the window is a scope, not an "
              f"attribution. Treat the total as +/-{abs(d)/dispatched*100:.0f}%.")
    print(f"  recorded total : {recorded:,}  <- usage.log `total:` (peak context)"
          if recorded else "  recorded total : n/a")
    print(f"  actual flow    : {cum:,}"
          + (f"  ({payload['understatement_x']}x)" if payload["understatement_x"] else ""))
    print(f"  cost (list)    : ${usd_total:,.2f}")
    print("  by class       : " + "  ".join(
        f"{k}={v:,}" for k, v in total.items()))
    print("  by model:")
    for k, v in sorted(by_model.items(), key=lambda kv: -kv[1]["usd"]):
        print(f"    {k:24} {v['agents']:3} agents  {v['requests']:5} requests  "
              f"${v['usd']:8,.2f}")
    if len(by_model) > 1:
        print("    (a transcript that switched model mid-pass is counted under "
              "each model it used, so `agents` can sum above the matched total)")
    if guessed_models:
        print(f"  ! unpriced models fell back to {UNKNOWN_MODEL_FALLBACK}: "
              + ", ".join(sorted(guessed_models)))
    if anomalies_total:
        print(f"  ! {anomalies_total} request(s) had duplicate records disagreeing "
              "on cache counters -- the collapse assumption is eroding; re-check "
              "the harness transcript format before trusting these figures.")

    b = payload.get("write_breakdown")
    if b and b["write"]:
        print("  cache-write budget:")
        print(f"    amplification  : {b['amplification']}x  "
              f"(sum writes / sum peak context; ~1.0 = each token written once)")
        rows = (("first", "first-turn prefix (written half only)"),
                ("rewrite", "re-write (cache lost between turns)"),
                ("new", "genuinely-new content"))
        if b["coherent"]:
            for k, label in rows:
                print(f"    {label:38} {b[k]:12,}  {b[k]/b['write']*100:5.1f}%")
        else:
            # A negative component means the model of the data is wrong. Do not
            # render it as a meaningful budget share; print raw counts and say
            # plainly that the decomposition is broken.
            print("    ! DECOMPOSITION INCOHERENT — a component is negative, so "
                  "shares are meaningless and are not shown.")
            for k, label in rows:
                print(f"    {label:38} {b[k]:12,}")
            print("      Investigate before quoting any of these figures.")
        # `turns` excludes each transcript's first request (no preceding turn to
        # measure a gap against), so it is `requests` minus `transcripts`.
        print(f"    re-write turns : {b['rewrite_turns']}/{b['turns']} "
              f"({b['rewrite_turns']/max(b['turns'],1)*100:.1f}%)"
              f"  [turns = {b['requests']} requests - {b['transcripts']} transcripts;"
              f" a first request has no preceding turn]")
        print("    re-write tokens by inter-turn gap: "
              + "  ".join(f"{k} {v/max(b['rewrite'],1)*100:.0f}%"
                          for k, v in b["rewrite_by_gap"].items()))
        if b["shrink_turns"]:
            print(f"    ({b['shrink_turns']} turn(s) where context shrank; their "
                  "vanished content is NOT counted as re-write)")
        if b["out_of_order"]:
            print(f"    ! {b['out_of_order']} adjacent pair(s) out of chronological "
                  "order — gap buckets for those are unreliable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
