#!/usr/bin/env python3
# pattern: imperative shell (I/O + reporting); pure matching core in the FUNCTIONAL CORE block
"""Cross-run finding-recurrence pilot — a no-new-logging outcome proxy.

Re-reviewing a project records whether a prior finding persists. Replicate
pairs estimate matcher plus sampling variance; reader A/B pairs mix that noise
with the reader treatment; temporal pairs provide the outcome proxy.

Observed persona output is materially stochastic, so disappearance alone is
not reliable evidence of a fix. Persistence on a later commit is the stronger
signal. The tool estimates the non-resampling floor from the supplied corpus
rather than embedding a private historical percentage.

`usage.log` supplies project/mode/calibration/run-dir metadata, findings come
from each run's snapshot, and persona aliases are canonicalized from frontmatter.

Usage: recurrence-pilot.py [--threshold 0.5] [--window-min 90] [--json]
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # runs as __main__ from any CWD
from persona_aliases import build_persona_aliases, canon_persona
from finding_match import SEV_RANK, norm_file, title_tokens, recurs

# ============================ FUNCTIONAL CORE ============================
# Pure: no I/O. The finding matcher (norm_file/title_tokens/finding_match/recurs +
# SEV_RANK) lives in finding_match.py, shared with subsample-analyzer.py.
# What's pure-but-pilot-specific stays here: cross-run pair classification.

def classify_pair(a, b, window_min):
    """a, b are run dicts (a earlier). Returns 'replicate'|'reader-ab'|'temporal'."""
    gap_min = abs(b["ts_epoch"] - a["ts_epoch"]) / 60.0
    same_event = gap_min <= window_min
    cal_a, cal_b = a["cal"], b["cal"]
    calib = {cal_a, cal_b} <= {"baseline", "reader"} and (cal_a or cal_b)
    if same_event and calib:
        if cal_a == cal_b:           # reader+reader (or baseline+baseline)
            return "replicate"
        return "reader-ab"           # baseline vs reader on identical code
    if same_event and cal_a == cal_b and cal_a not in (None, "", "-"):
        return "replicate"
    return "temporal"


# ============================ IMPERATIVE SHELL ============================

def ts_to_epoch(ts):
    # '20260601T055242Z' -> UTC POSIX epoch (float). Uses datetime.strptime so
    # calendar month lengths are exact — the old hand-rolled formula treated every
    # month as 31 days, making a 30-min gap across a June→July boundary compute as
    # ~1470 min and misclassify replicate→temporal (f14).
    if not ts:
        return 0
    try:
        dt = datetime.strptime(ts, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return 0


def parse_usage_log(path):
    runs = []
    for ln in path.read_text().splitlines():
        parts = [p.strip() for p in ln.split("|")]
        if len(parts) < 6:
            continue
        date, proj, mode = parts[0], parts[1], parts[2]
        m = re.search(r"run:(\S+)", ln)
        cal = re.search(r"cal:(\w+)", ln)
        tm = re.search(r"(\d{8}T\d{6}Z)", ln)
        if not (m and tm):
            continue
        rundir = Path(m.group(1).replace("$HOME", str(Path.home())).replace("~", str(Path.home())))
        runs.append({
            "date": date, "project": proj.strip().lower(), "project_raw": proj.strip(),
            "mode": mode, "cal": (cal.group(1) if cal else None),
            "ts": tm.group(1), "ts_epoch": ts_to_epoch(tm.group(1)), "run_dir": rundir,
        })
    return runs


def load_findings(run_dir, amap):
    """Normalized findings from a run's snapshot. [] if absent/unparseable."""
    p = run_dir / "findings-snapshot.json"
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text())
    except Exception:
        return None
    out = []
    for f in (data.get("findings") or []):
        raw_file = f.get("file") or f.get("location") or ""
        title = f.get("title") or ""
        sev = (f.get("severity") or "noted").lower()
        if sev not in SEV_RANK:
            sev = "noted"
        ps = [canon_persona(x, amap) for x in (f.get("personas") or [])]
        out.append({
            "nfile": norm_file(raw_file), "title": title, "toks": title_tokens(title),
            "sev": sev, "personas": ps,
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-dir", default=str(Path.home() / ".angel" / "runs"))
    ap.add_argument("--usage-log", default=str(Path.home() / ".claude" / "skills" / "angel" / "usage.log"))
    ap.add_argument("--threshold", type=float, default=0.5, help="title overlap-coefficient to call a match")
    ap.add_argument("--window-min", type=float, default=90.0, help="same-event window (min) for replicate/reader-ab")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--skill-dir", default=None,
                    help="path to skill root for alias map (default: parent of this script); "
                         "mirrors validate-personas.py --skill-dir for fixture testing")
    args = ap.parse_args()

    skill_dir = Path(args.skill_dir).resolve() if args.skill_dir else Path(__file__).resolve().parent.parent
    amap = build_persona_aliases(skill_dir)

    usage = Path(args.usage_log)
    if not usage.is_file():
        print(f"no usage.log: {usage}", file=sys.stderr)
        sys.exit(1)

    runs = parse_usage_log(usage)
    # Attach findings; keep full-mode runs that have a parseable snapshot.
    by_project = defaultdict(list)
    display = {}
    for r in runs:
        display.setdefault(r["project"], r["project_raw"])
        if r["project_raw"] != r["project_raw"].lower():
            display[r["project"]] = r["project_raw"]
        if r["mode"] != "full":
            continue
        fs = load_findings(r["run_dir"], amap)
        if fs is None:
            continue
        r["findings"] = fs
        by_project[r["project"]].append(r)

    # Pair consecutive full+snapshot runs within each project (time order).
    BUCKETS = ("replicate", "reader-ab", "temporal")
    pairs = {b: [] for b in BUCKETS}            # (project, a, b)
    for proj, rs in by_project.items():
        rs.sort(key=lambda x: x["ts_epoch"])
        for a, b in zip(rs, rs[1:]):
            pairs[classify_pair(a, b, args.window_min)].append((proj, a, b))

    # Per-bucket recurrence + per-persona breakdown (Important+ only for the proxy).
    def analyze(bucket_pairs):
        tot = rec = ip_tot = ip_rec = 0
        per = defaultdict(lambda: {"earlier": 0, "recur": 0})  # persona -> counts (Important+)
        for proj, a, b in bucket_pairs:
            for fe in a["findings"]:
                r = recurs(fe, b["findings"], args.threshold)
                tot += 1
                rec += int(r)
                if SEV_RANK[fe["sev"]] >= 2:  # Important+
                    ip_tot += 1
                    ip_rec += int(r)
                    for p in (fe["personas"] or ["(unattributed)"]):
                        per[p]["earlier"] += 1
                        per[p]["recur"] += int(r)
        return {"tot": tot, "rec": rec, "ip_tot": ip_tot, "ip_rec": ip_rec, "per": per}

    results = {b: analyze(pairs[b]) for b in BUCKETS}

    # Stochastic-loss floor: on replicate pairs (identical code+config) any
    # disappearance is non-resampling, not a fix. This is the noise floor that
    # confounds the temporal proxy — a temporal "disappearance" is only a fix
    # ABOVE this rate. Corrected fix-rate = (d_temporal - d_floor)/(1 - d_floor).
    rep = results["replicate"]
    floor_ip = (rep["ip_tot"] - rep["ip_rec"]) / rep["ip_tot"] if rep["ip_tot"] else None

    if args.json:
        def corrected_fix(d_t):
            if floor_ip is None or d_t is None or (1 - floor_ip) <= 0:
                return None
            return max(0.0, (d_t - floor_ip) / (1 - floor_ip))

        buckets = {}
        for b in BUCKETS:
            R = results[b]
            d_ip = (R["ip_tot"] - R["ip_rec"]) / R["ip_tot"] if R["ip_tot"] else None
            buckets[b] = {
                "findings_compared": R["tot"],
                "recurred": R["rec"],
                "recurrence_rate": (R["rec"] / R["tot"]) if R["tot"] else None,
                "importantplus_disappear_rate": d_ip,
                "per_persona_importantplus": {
                    p: {"earlier": v["earlier"], "recurred": v["recur"],
                        "disappeared": v["earlier"] - v["recur"],
                        "disappear_rate": (v["earlier"] - v["recur"]) / v["earlier"] if v["earlier"] else None}
                    for p, v in sorted(R["per"].items())
                },
            }
            if b == "temporal":
                buckets[b]["noise_floor_importantplus"] = floor_ip
                buckets[b]["corrected_fix_rate_importantplus"] = corrected_fix(d_ip)
        out = {
            "params": {"threshold": args.threshold, "window_min": args.window_min},
            "coverage": {
                "projects_with_full_snapshots": len(by_project),
                "pairs": {b: len(pairs[b]) for b in BUCKETS},
            },
            "stochastic_floor_importantplus": floor_ip,
            "buckets": buckets,
        }
        print(json.dumps(out, indent=2))
        return

    L = ["# NineAngel finding-recurrence pilot", ""]
    L.append(f"Params: title-overlap threshold **{args.threshold}**, same-event window **{args.window_min:.0f} min**. "
             f"Persona keys canonicalized from frontmatter; metadata joined from usage.log.")
    L.append("")
    L.append(f"Coverage: **{len(by_project)}** projects have ≥1 full run with a parseable snapshot. "
             f"Pairs by type — replicate: **{len(pairs['replicate'])}**, "
             f"reader-ab: **{len(pairs['reader-ab'])}**, temporal: **{len(pairs['temporal'])}**.")
    L.append("")
    L.append("- **replicate** (same code+config): recurrence ≈ matcher recall × persona reproducibility. Low = matcher false-neg or sampling noise.")
    L.append("- **reader-ab** (same code, reader off vs on): confounded by the reader treatment — not a clean control.")
    L.append("- **temporal** (later commit): the fix-disposition proxy. NOTE the confound below — disappearance is NOT a clean fix signal.")
    if floor_ip is not None:
        L.append("")
        L.append(f"**Stochastic floor (Important+): {100*floor_ip:.0f}% of findings disappear on IDENTICAL code+config** "
                 f"(replicate pairs). So a temporal disappearance is a *fix* only above this floor: "
                 f"corrected_fix ≈ (d − {floor_ip:.2f})/(1 − {floor_ip:.2f}). Persistence (re-appearance on a later commit) "
                 f"is the robust signal — it is unaffected by non-resampling; disappearance is heavily confounded.")
    L.append("")
    for b in BUCKETS:
        R = results[b]
        tot, rec, per = R["tot"], R["rec"], R["per"]
        rate = f"{100*rec/tot:.0f}%" if tot else "—"
        L.append(f"## {b}")
        if not tot:
            note = " — accrues as projects get re-reviewed full-mode on later commits (e.g. the Blindspot experiment re-runs)." if b == "temporal" else ""
            L.append(f"_No findings compared ({len(pairs[b])} pairs){note}_")
            L.append("")
            continue
        L.append(f"- {tot} earlier-run findings compared; **{rec} recurred ({rate})**, {tot-rec} disappeared.")
        if b == "temporal":
            d_ip = (R["ip_tot"] - R["ip_rec"]) / R["ip_tot"] if R["ip_tot"] else None
            if d_ip is not None and floor_ip is not None and (1 - floor_ip) > 0:
                corr = max(0.0, (d_ip - floor_ip) / (1 - floor_ip))
                L.append(f"- Important+ raw disappearance {100*d_ip:.0f}%; **noise-floor-corrected fix-rate ≈ {100*corr:.0f}%**.")
            L.append("- Per-persona — `persisted` = re-found on later commit (robust: chronic/unfixed); raw `disappeared` is confounded by the stochastic floor above:")
        elif b == "replicate":
            L.append("- Per-persona reproducibility (Important+) — higher = more reproducible / better matcher recall:")
        else:
            L.append("- Per-persona recurrence (Important+):")
        L.append("")
        head = "persisted" if b == "temporal" else "recurred"
        L.append(f"| persona | Important+ earlier | {head} | disappeared | rate |")
        L.append("|---|--:|--:|--:|--:|")
        rows = sorted(per.items(), key=lambda kv: -kv[1]["earlier"])
        for p, v in rows:
            e, r = v["earlier"], v["recur"]
            if b == "temporal":
                metric = f"{100*r/e:.0f}% persist" if e else "—"
            else:
                metric = f"{100*r/e:.0f}% kept" if e else "—"
            L.append(f"| {p} | {e} | {r} | {e-r} | {metric} |")
        L.append("")
    print("\n".join(L))


if __name__ == "__main__":
    main()
