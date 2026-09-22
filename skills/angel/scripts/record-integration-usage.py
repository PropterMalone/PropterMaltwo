#!/usr/bin/env python3
"""Append one typed reducer/fallback usage record without conflating context and spend."""
import argparse
import datetime
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--telemetry")
    ap.add_argument("--degraded-reason")
    args = ap.parse_args()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    if args.telemetry and Path(args.telemetry).is_file():
        t = json.loads(Path(args.telemetry).read_text())
        inp, out = t.get("input_tokens"), t.get("output_tokens")
        row = {"phase": "integrator", "name": "semantic-reducer", "model": t.get("model"),
               "backend": "codex-subscription", "total_tokens": t.get("total_tokens"),
               "tool_uses": 0, "duration_ms": t.get("duration_ms"), "started_at": None,
               "ended_at": now, "reader_pack": False,
               # Codex reports cumulative turn usage, not a measured initial or
               # peak context. Preserve it under truthful names and leave the
               # legacy context fields unknown rather than fabricating them.
               "input_tokens": inp, "output_tokens": out,
               "initial_context_tokens": None, "peak_context_tokens": None,
               "request_count": t.get("request_count"),
               "turn_count": t.get("turn_count"),
               "note": "ChatGPT-authenticated structured-output reducer"}
    else:
        row = {"phase": "integrator", "name": "deterministic-union", "model": None,
               "backend": "deterministic", "total_tokens": 0, "tool_uses": 0,
               "duration_ms": 0, "started_at": now, "ended_at": now, "reader_pack": False,
               "initial_context_tokens": 0, "peak_context_tokens": 0, "request_count": 0,
               "note": f"integration_degraded:{args.degraded_reason}"}
    with (Path(args.run_dir) / "usage.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, separators=(",", ":")) + "\n")


if __name__ == "__main__": main()
