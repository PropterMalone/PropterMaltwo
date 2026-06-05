#!/usr/bin/env python3
# pattern: imperative shell
"""Mine ~/.angel/runs/ for cross-run NineAngel analytics.

One tool, two audiences:
  - improve 9A  -> per-persona value table (does each persona earn its slot?
                   solo vs. shared findings, Important+ unique rate, noise mix)
  - show value  -> portfolio summary + a Critical-findings ledger (what 9A caught)

Joins each run's findings-snapshot (per-finding `personas` attribution) with
usage.json cost when present. Defensive about historical layout drift: snapshots
live under several filenames; cost is absent on older runs. Coverage is reported
so thin data is never mistaken for a clean signal.

Usage: mine-runs.py [--runs-dir DIR] [--since YYYY-MM-DD] [--json]
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

# Snapshot filename drift across run history. First parseable file with a
# `findings` list wins. The canonical name (post-2026-05-30) is first.
SNAPSHOT_CANDIDATES = [
    "findings-snapshot.json",
    "integrator-snapshot.json",
    "snapshot.json",
    "integrator-output.json",
]
SEV = ["critical", "important", "minor", "noted"]


def load_snapshot(run_dir):
    for name in SNAPSHOT_CANDIDATES:
        p = run_dir / name
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text())
        except Exception:
            continue
        if isinstance(data, dict) and isinstance(data.get("findings"), list):
            return data, name
    return None, None


def load_usage(run_dir):
    p = run_dir / "usage.json"
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text())
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def load_dispositions(run_dir):
    p = run_dir / "dispositions.json"
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def run_date(data, run_dir):
    d = (data or {}).get("date")
    if d:
        return d
    stem = run_dir.name[:8]
    if len(stem) == 8 and stem.isdigit():
        return f"{stem[:4]}-{stem[4:6]}-{stem[6:8]}"
    return "????-??-??"


def commas(n):
    return f"{n:,}" if isinstance(n, (int, float)) else "—"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-dir", default=str(Path.home() / ".angel" / "runs"))
    ap.add_argument("--since", default=None, help="YYYY-MM-DD floor (inclusive)")
    ap.add_argument("--json", action="store_true", help="emit machine JSON instead of report")
    args = ap.parse_args()

    runs_dir = Path(args.runs_dir)
    if not runs_dir.is_dir():
        print(f"no runs dir: {runs_dir}", file=sys.stderr)
        sys.exit(1)

    run_dirs = sorted(d for d in runs_dir.iterdir() if d.is_dir())
    total = len(run_dirs)
    parsed = 0
    with_usage = 0

    pruns = defaultdict(int)                      # runs the persona participated in
    pfind = defaultdict(int)                      # total findings caught (any attribution)
    psolo = defaultdict(int)                      # solo findings (only this persona)
    psev = defaultdict(lambda: defaultdict(int))  # persona -> sev -> count (total)
    psev_solo = defaultdict(lambda: defaultdict(int))
    ptokens = defaultdict(int)
    ptoken_runs = defaultdict(int)
    pcited = defaultdict(int)                     # findings with cited-spec/code-site evidence
    pev = defaultdict(int)                        # findings carrying any evidence value
    pdisp = defaultdict(int)                      # findings with a recorded disposition
    pfp = defaultdict(int)                        # findings dispositioned rejected-wrong (false positives)
    runs_with_evidence = 0
    runs_with_disp = 0

    sev_totals = defaultdict(int)
    verdict_counts = defaultdict(int)
    projects = set()
    criticals = []                               # (date, project, title, personas)
    overlap = defaultdict(lambda: defaultdict(int))
    runs_meta = []

    for d in run_dirs:
        data, sname = load_snapshot(d)
        if not data:
            continue
        date = run_date(data, d)
        if args.since and (date.startswith("?") or date < args.since):
            continue  # exclude unknown-date runs from a --since window (conservative)
        parsed += 1
        usage = load_usage(d)
        if usage:
            with_usage += 1
        dispmap = load_dispositions(d)
        if dispmap:
            runs_with_disp += 1
        if any(f.get("evidence") for f in (data.get("findings") or [])):
            runs_with_evidence += 1

        project = data.get("project") or d.name
        projects.add(project)
        verdict = (data.get("verdict") or "?").strip()
        verdict_counts[verdict] += 1
        mode = data.get("mode") or "?"
        findings = data.get("findings") or []

        finding_personas = set()
        for f in findings:
            for p in (f.get("personas") or []):
                finding_personas.add(p)
        participants = set(data.get("personas_run") or []) | finding_personas
        for p in participants:
            pruns[p] += 1

        for f in findings:
            sev = (f.get("severity") or "noted").lower()
            if sev not in SEV:
                sev = "noted"
            sev_totals[sev] += 1
            ps = f.get("personas") or []
            ev = f.get("evidence")
            fid = f.get("id")
            d_entry = dispmap.get(fid) if fid else None
            d_val = d_entry.get("disposition") if isinstance(d_entry, dict) else None
            if sev == "critical":
                criticals.append((date, project, f.get("title") or "(untitled)", ",".join(ps)))
            for p in ps:
                pfind[p] += 1
                psev[p][sev] += 1
                if ev:
                    pev[p] += 1
                    if ev in ("cited-spec", "code-site"):
                        pcited[p] += 1
                if d_val:
                    pdisp[p] += 1
                    if d_val == "rejected-wrong":
                        pfp[p] += 1
            if len(ps) == 1:
                psolo[ps[0]] += 1
                psev_solo[ps[0]][sev] += 1
            if sev in ("critical", "important"):  # consolidation signal: co-catch at Important+
                for a in ps:
                    for b in ps:
                        if a != b:
                            overlap[a][b] += 1

        if usage:
            for pp in (usage.get("totals", {}).get("personas") or []):
                nm, tk = pp.get("name"), pp.get("total_tokens")
                if nm and isinstance(tk, (int, float)):
                    ptokens[nm] += int(tk)
                    ptoken_runs[nm] += 1

        runs_meta.append({
            "date": date, "project": project, "mode": mode, "verdict": verdict,
            "snapshot": sname, "has_usage": bool(usage), "findings": len(findings),
        })

    def fp_rate(p):
        return pfp[p] / pdisp[p] if pdisp[p] else 0.0

    # solo Important+ first, then LOW fp% (negate under reverse), then volume.
    personas = sorted(
        set(pruns) | set(pfind),
        key=lambda p: (psev_solo[p]["critical"] + psev_solo[p]["important"], -fp_rate(p), psolo[p], pfind[p]),
        reverse=True,
    )

    # Unique persona pairs by Important+ co-occurrence (consolidation candidates).
    pairs = []
    seen = set()
    for a in overlap:
        for b in overlap[a]:
            key = tuple(sorted((a, b)))
            if key in seen:
                continue
            seen.add(key)
            pairs.append((overlap[a][b], key[0], key[1]))
    pairs.sort(reverse=True)

    if args.json:
        out = {
            "coverage": {"run_dirs": total, "parsed": parsed, "with_usage": with_usage,
                         "with_evidence": runs_with_evidence, "with_dispositions": runs_with_disp},
            "personas": {
                p: {
                    "runs": pruns[p], "findings": pfind[p], "solo": psolo[p],
                    "solo_important_plus": psev_solo[p]["critical"] + psev_solo[p]["important"],
                    "severity_total": dict(psev[p]), "severity_solo": dict(psev_solo[p]),
                    "cited": pcited[p], "evidence_present": pev[p],
                    "disposed": pdisp[p], "false_positives": pfp[p],
                    "tokens": ptokens[p] if ptoken_runs[p] else None,
                    "tokens_runs": ptoken_runs[p],
                } for p in personas
            },
            "portfolio": {
                "runs": parsed, "projects": sorted(projects),
                "severity_totals": dict(sev_totals), "verdicts": dict(verdict_counts),
                "criticals": [
                    {"date": dt, "project": pr, "title": ti, "personas": pe}
                    for dt, pr, ti, pe in criticals
                ],
                "overlap_important_plus": [
                    {"pair": [a, b], "count": c} for c, a, b in pairs
                ],
            },
            "runs": runs_meta,
        }
        print(json.dumps(out, indent=2))
        return

    L = []
    L.append("# NineAngel cross-run analytics")
    L.append("")
    L.append(f"Coverage: **{parsed}/{total}** run dirs had a parseable snapshot; "
             f"**{with_usage}** had `usage.json` (cost), "
             f"**{runs_with_evidence}** carried evidence tags, "
             f"**{runs_with_disp}** had dispositions. "
             f"{parsed} runs across {len(projects)} projects.")
    if parsed < total:
        L.append(f"_{total - parsed} run dirs skipped — no parseable findings-snapshot "
                 f"(historical layout drift; the canonical `findings-snapshot.json` is forward-complete from 2026-05-30)._")
    L.append("")

    L.append("## Per-persona value")
    L.append("")
    L.append("Sorted by solo Important+ (unique high-severity catches — the earns-its-slot signal). "
             "`%solo` = share of this persona's findings no other persona caught. "
             "`cited%` = share backed by a spec/code-site citation vs. inference. "
             "`fp%` = false-positive rate from recorded dispositions (n = findings dispositioned). "
             "cited%/fp% stay blank until evidence/disposition data accrues — solo volume alone does not mean correct.")
    L.append("")
    L.append("| persona | runs | finds | solo | soloI+ | %solo | cited% | fp% (n) | C/I/M/N | tokens (n) |")
    L.append("|---|--:|--:|--:|--:|--:|--:|--:|---|--:|")
    for p in personas:
        soloip = psev_solo[p]["critical"] + psev_solo[p]["important"]
        pct = f"{100*psolo[p]/pfind[p]:.0f}%" if pfind[p] else "—"
        cited = f"{100*pcited[p]/pev[p]:.0f}%" if pev[p] else "—"
        fp = f"{100*pfp[p]/pdisp[p]:.0f}% ({pdisp[p]})" if pdisp[p] else "—"
        cimn = "/".join(str(psev[p][s]) for s in SEV)
        tok = f"{commas(ptokens[p])} ({ptoken_runs[p]})" if ptoken_runs[p] else "—"
        L.append(f"| {p} | {pruns[p]} | {pfind[p]} | {psolo[p]} | {soloip} | {pct} | {cited} | {fp} | {cimn} | {tok} |")
    L.append("")

    L.append("## Persona overlap (Important+ co-occurrence)")
    L.append("")
    if pairs:
        L.append("Pairs that repeatedly co-catch the same Critical/Important finding — high counts flag "
                 "consolidation candidates (DESIGN.md roster discipline).")
        L.append("")
        L.append("| pair | shared Important+ findings |")
        L.append("|---|--:|")
        for cnt, a, b in pairs[:10]:
            L.append(f"| {a} + {b} | {cnt} |")
    else:
        L.append("_No Important+ co-occurrences yet._")
    L.append("")

    L.append("## Portfolio value (what 9A has caught)")
    L.append("")
    sev_line = ", ".join(f"{sev_totals[s]} {s}" for s in SEV if sev_totals[s])
    L.append(f"- Findings across {parsed} runs: {sev_line or '(none)'}")
    L.append(f"- Verdicts: " + ", ".join(f"{v} ×{n}" for v, n in sorted(verdict_counts.items(), key=lambda kv: -kv[1])))
    L.append(f"- Projects: {len(projects)}")
    L.append("")
    if criticals:
        L.append("### Critical-findings ledger")
        L.append("")
        L.append("| date | project | finding | caught by |")
        L.append("|---|---|---|---|")
        for dt, pr, ti, pe in sorted(criticals):
            ti = (ti.replace("|", "\\|").replace("`", "'")
                    .replace("[", "\\[").replace("]", "\\]").replace("\n", " "))
            pr = pr.replace("|", "\\|").replace("\n", " ")
            L.append(f"| {dt} | {pr} | {ti} | {pe} |")
        L.append("")

    print("\n".join(L))


if __name__ == "__main__":
    main()
