#!/usr/bin/env python3
"""Pair baseline+reader /angel calibration runs and emit reader-calibration.json
markers + a cross-project summary. Deterministic — no LLM.

Source of truth: ~/.claude/skills/angel/usage.log (each completed run appends a
line carrying `cal:<tag>` and `run:<dir>`). For each project we take the LATEST
valid baseline and reader run, read both run dirs' usage.json (cost) +
findings-snapshot.json (findings), compute the §8.5.2 delta with finding-level
lost/gained matching, and write the §8.5.3 marker to the project's memory dir.

Usage: python3 finalize-calibration.py [--write] [--project NAME] [--projects-root DIR]
  (default is dry-run: prints the summary, writes nothing unless --write)

Env overrides (matching the sibling scripts' pattern): ANGEL_USAGE_LOG for the
usage.log path, ANGEL_PROJECTS_ROOT for the projects root (--projects-root wins).
"""
import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime, timezone

HOME = Path.home()
USAGE_LOG = Path(os.environ.get("ANGEL_USAGE_LOG", HOME / ".claude/skills/angel/usage.log"))
PROJECTS_ROOT = Path(os.environ.get("ANGEL_PROJECTS_ROOT", HOME / "Projects"))


def parse_usage_log():
    """Return {proj_lower: {tag: [run_dicts...]}} in chronological (file) order."""
    runs = {}
    if not USAGE_LOG.exists():
        return runs
    for line in USAGE_LOG.read_text(errors="replace").splitlines():
        m_cal = re.search(r"cal:(\w+)", line)
        m_run = re.search(r"run:(\S+)", line)
        if not m_cal or not m_run:
            continue
        tag = m_cal.group(1)
        if tag not in ("baseline", "reader"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2:
            continue
        project = parts[1]
        m_f = re.search(r"(\d+)C/(\d+)I/(\d+)M/(\d+)N", line)
        m_tot = re.search(r"total:(\d+|null)", line)
        rec = {
            "project": project,
            "tag": tag,
            "run_dir": m_run.group(1),
            "log_cimn": tuple(int(x) for x in m_f.groups()) if m_f else None,
            "total": None if (not m_tot or m_tot.group(1) == "null") else int(m_tot.group(1)),
        }
        runs.setdefault(project.lower(), {}).setdefault(tag, []).append(rec)
    return runs


def valid_run(rec):
    """A run is usable if its dir exists with a parseable snapshot + usage.json,
    its tokens are measured, and it found something (drops null/all-zero failures)."""
    rd = Path(rec["run_dir"])
    snap_p, uj_p = rd / "findings-snapshot.json", rd / "usage.json"
    if not snap_p.exists() or not uj_p.exists():
        return None
    if rec["total"] is None:
        return None
    if rec["log_cimn"] == (0, 0, 0, 0):
        return None
    try:
        snap = json.loads(snap_p.read_text())
        uj = json.loads(uj_p.read_text())
    except Exception:
        return None
    return {"snap": snap, "uj": uj, "snap_path": str(snap_p)}


def latest_valid(rec_list):
    """Last valid run in file order (chronological) wins."""
    for rec in reversed(rec_list or []):
        loaded = valid_run(rec)
        if loaded:
            return rec, loaded
    return None, None


def ci_findings(snap):
    """Critical+Important findings, normalized for matching."""
    out = []
    for f in snap.get("findings") or []:
        sev = (f.get("severity") or "").lower()
        if sev not in ("critical", "important"):
            continue
        title = str(f.get("title") or f.get("summary") or "").lower()
        out.append({
            "severity": sev,
            "file": os.path.basename(str(f.get("file") or "")),
            "line": int(re.sub(r"\D", "", str(f.get("line") or "0")) or 0),
            "title": title,
            "tokens": set(re.findall(r"[a-z0-9]+", title)),
            "personas": set(f.get("personas") or []),
        })
    return out


def all_findings(snap):
    """Every finding (any severity), for match lookups (reclassification check)."""
    out = []
    for f in snap.get("findings") or []:
        title = str(f.get("title") or f.get("summary") or "").lower()
        out.append({
            "file": os.path.basename(str(f.get("file") or "")),
            "line": int(re.sub(r"\D", "", str(f.get("line") or "0")) or 0),
            "tokens": set(re.findall(r"[a-z0-9]+", title)),
            "personas": set(f.get("personas") or []),
        })
    return out


def matches(a, b):
    """Heuristic: same file & line within ±3, OR strong title-token overlap.

    The file-line branch requires at least one KNOWN line: findings without a
    line number parse as 0, and 0==0 used to collapse two DISTINCT same-file
    findings into one match — a reader run that dropped a critical scored
    lost_critical=0. When both lines are unknown, fall through to title tokens."""
    if (a["file"] and a["file"] == b["file"]
            and (a["line"] or b["line"]) and abs(a["line"] - b["line"]) <= 3):
        return True
    ta, tb = a["tokens"], b["tokens"]
    if ta and tb:
        ov = len(ta & tb) / max(1, min(len(ta), len(tb)))
        if ov >= 0.75 or (ov >= 0.55 and (a["personas"] & b["personas"])):
            return True
    return False


def lost_gained(base_ci, reader_all, reader_ci, base_all):
    """Counts of baseline C/I absent from reader (lost) and reader C/I absent
    from baseline (gained), matched against ALL findings (so a reclassification
    to a lower severity is NOT counted as a loss)."""
    lost = {"critical": 0, "important": 0}
    for f in base_ci:
        if not any(matches(f, r) for r in reader_all):
            lost[f["severity"]] += 1
    gained = {"critical": 0, "important": 0}
    for f in reader_ci:
        if not any(matches(f, b) for b in base_all):
            gained[f["severity"]] += 1
    return lost, gained


def real_dir(project):
    """Resolve the actual project dir case-insensitively (usage.log names drift)."""
    if not PROJECTS_ROOT.exists():
        return None
    for d in PROJECTS_ROOT.iterdir():
        if d.is_dir() and d.name.lower() == project.lower():
            return d
    return None


def pct(new, old):
    return None if not old else round((new - old) / old * 100, 1)


def main():
    global PROJECTS_ROOT
    write = "--write" in sys.argv
    only = None
    if "--project" in sys.argv:
        only = sys.argv[sys.argv.index("--project") + 1].lower()
    if "--projects-root" in sys.argv:
        PROJECTS_ROOT = Path(sys.argv[sys.argv.index("--projects-root") + 1]).expanduser()

    runs = parse_usage_log()
    rows = []
    aggregate = {"lost_c": 0, "lost_i": 0, "gained_c": 0, "gained_i": 0,
                 "tok_deltas": [], "wall_deltas": [], "pairs": 0}

    for proj_lower in sorted(runs):
        if only and proj_lower != only:
            continue
        b_rec, b = latest_valid(runs[proj_lower].get("baseline"))
        r_rec, r = latest_valid(runs[proj_lower].get("reader"))
        if not b or not r:
            rows.append((proj_lower, "INCOMPLETE",
                         f"baseline={'ok' if b else 'missing'} reader={'ok' if r else 'missing'}"))
            continue

        b_tok = b["uj"].get("totals", {}).get("total_tokens") or b_rec["total"]
        r_tok = r["uj"].get("totals", {}).get("total_tokens") or r_rec["total"]
        b_wall = b["uj"].get("totals", {}).get("wall_seconds")
        r_wall = r["uj"].get("totals", {}).get("wall_seconds")
        b_find = b["uj"].get("findings") or {}
        r_find = r["uj"].get("findings") or {}

        lost, gained = lost_gained(ci_findings(b["snap"]), all_findings(r["snap"]),
                                   ci_findings(r["snap"]), all_findings(b["snap"]))

        aggregate["lost_c"] += lost["critical"]
        aggregate["lost_i"] += lost["important"]
        aggregate["gained_c"] += gained["critical"]
        aggregate["gained_i"] += gained["important"]
        aggregate["pairs"] += 1
        tok_d = pct(r_tok, b_tok)
        wall_d = pct(r_wall, b_wall) if (b_wall and r_wall) else None
        if tok_d is not None:
            aggregate["tok_deltas"].append(tok_d)
        if wall_d is not None:
            aggregate["wall_deltas"].append(wall_d)

        flag = "  <-- LOST CRITICAL" if lost["critical"] else ""
        rows.append((proj_lower,
                     f"C {b_find.get('critical','?')}->{r_find.get('critical','?')} "
                     f"I {b_find.get('important','?')}->{r_find.get('important','?')}",
                     f"lostC={lost['critical']} lostI={lost['important']} "
                     f"gainC={gained['critical']} gainI={gained['important']} "
                     f"tok={tok_d:+}%" + (f" wall={wall_d:+}%" if wall_d is not None else "") + flag))

        if write:
            d = real_dir(proj_lower)
            if not d:
                rows[-1] = (rows[-1][0], rows[-1][1],
                            rows[-1][2] + f"  (no dir under {PROJECTS_ROOT}; marker skipped)")
                continue
            encoded = str(d).replace("/", "-")
            mem = HOME / ".claude/projects" / encoded / "memory"
            mem.mkdir(parents=True, exist_ok=True)
            marker = {
                "version": 1, "project": d.name,
                "calibrated_at": datetime.now(timezone.utc).isoformat(),
                "review_mode": "full",
                "baseline": {"snapshot": b["snap_path"], "total_tokens": b_tok,
                             "wall_clock_s": b_wall, "findings": b_find},
                "reader": {"snapshot": r["snap_path"], "total_tokens": r_tok,
                           "wall_clock_s": r_wall, "findings": r_find},
                "delta": {"total_tokens_pct": tok_d, "wall_clock_pct": wall_d,
                          "critical_lost": lost["critical"], "important_lost": lost["important"],
                          "critical_gained": gained["critical"], "important_gained": gained["important"],
                          # cost/wall come from the per-Agent meter (trustworthy).
                          # lost/gained use a text-match heuristic and are an UPPER BOUND
                          # on true losses — they miss reworded/cross-file severity
                          # reclassifications (e.g. a Critical surfacing as "noted").
                          "lost_gained_method": "text-match-heuristic-upper-bound"},
            }
            (mem / "reader-calibration.json").write_text(json.dumps(marker, indent=2))

    # Render
    print(f"\n{'PROJECT':<20} {'CRIT/IMP base->reader':<24} DELTA")
    print("-" * 92)
    for name, cimn, detail in rows:
        print(f"{name:<20} {cimn:<24} {detail}")
    a = aggregate
    avg = lambda xs: round(sum(xs) / len(xs), 1) if xs else None
    print("-" * 92)
    print(f"\nPAIRS: {a['pairs']}  |  GATE FLOOR (lost Criticals across all projects): {a['lost_c']}"
          f"  |  lost Important: {a['lost_i']}")
    print(f"gained Critical: {a['gained_c']}  gained Important: {a['gained_i']}")
    print(f"avg token delta (reader vs baseline): {avg(a['tok_deltas'])}%   "
          f"avg wall delta: {avg(a['wall_deltas'])}%")
    print("\nNOTE: lost/gained are a TEXT-MATCH UPPER BOUND — they count reworded or")
    print("cross-file severity reclassifications (e.g. Critical->noted) as losses.")
    print("Trust the metered token/wall deltas; treat finding losses as flags for review.")
    print(f"\nPrimary verdict (cost/speed, metered): reader = "
          f"{avg(a['tok_deltas']):+}% tokens, {avg(a['wall_deltas']):+}% wall vs baseline. "
          f"{'Reader fails its cost premise (more expensive).' if (avg(a['tok_deltas']) or 0) > 0 else 'Reader cheaper.'}")
    print(f"\n{'(dry-run; pass --write to emit markers)' if not write else 'markers written.'}")


if __name__ == "__main__":
    main()
