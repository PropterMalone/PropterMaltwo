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

sys.path.insert(0, str(Path(__file__).resolve().parent))  # runs as __main__ from any CWD
from angel_corpus import SNAPSHOT_CANDIDATES, in_scope, load_snapshot, run_date  # noqa: F401
from persona_aliases import build_persona_aliases, canon_persona

SEV = ["critical", "important", "minor", "noted"]


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






def commas(n):
    return f"{n:,}" if isinstance(n, (int, float)) else "—"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-dir", default=str(Path.home() / ".angel" / "runs"))
    ap.add_argument("--since", default=None, help="YYYY-MM-DD floor (inclusive)")
    ap.add_argument("--json", action="store_true", help="emit machine JSON instead of report")
    ap.add_argument("--skill-dir", default=None,
                    help="path to skill root for alias map (default: parent of this script); "
                         "mirrors validate-personas.py --skill-dir for fixture testing")
    args = ap.parse_args()

    skill_dir = Path(args.skill_dir).resolve() if args.skill_dir else Path(__file__).resolve().parent.parent
    amap = build_persona_aliases(skill_dir)

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
    pfp = defaultdict(int)                        # false positives: human rejected-wrong OR machine REFUTED
    pfp_human = defaultdict(int)                  # human rejected-wrong only
    pfp_machine = defaultdict(int)                # machine REFUTED only
    # Severity accuracy: the verifier's structured opinion on whether the filed
    # severity matched the verified mechanism. Missing opinions are not counted,
    # so silence never inflates the denominator.
    psev_op = defaultdict(lambda: defaultdict(int))
    runs_with_evidence = 0
    runs_with_disp = 0

    sev_totals = defaultdict(int)
    verdict_counts = defaultdict(int)
    projects = set()
    criticals = []                               # (date, project, title, personas)
    overlap = defaultdict(lambda: defaultdict(int))
    runs_meta = []
    project_display = {}  # lower-key -> best display casing (case-insensitive project keying)

    def register_project(key, raw):
        cur = project_display.get(key)
        # Prefer a cased name (e.g. "Subplot") over an all-lowercase variant ("subplot").
        if cur is None or (raw != raw.lower() and cur == cur.lower()):
            project_display[key] = raw

    for d in run_dirs:
        data, sname, _errors = load_snapshot(d)
        if not data:
            continue
        date = run_date(data, d)
        if args.since and not in_scope(date, args.since):
            continue  # exclude unknown-date runs from a --since window (conservative)
        parsed += 1
        usage = load_usage(d)
        if usage:
            with_usage += 1
        dispmap = load_dispositions(d)
        # finalize-run now emits a skeleton with every finding at "no-record"
        # (plus an optional top-level experiment:true bool) — placeholders,
        # not triage. Only real dispositions count toward coverage/precision.
        if any(isinstance(v, dict) and v.get("disposition") not in (None, "no-record")
               for v in dispmap.values()):
            runs_with_disp += 1
        if any(f.get("evidence") for f in (data.get("findings") or [])):
            runs_with_evidence += 1

        proj_raw = (data.get("project") or d.name).strip()
        project = proj_raw.lower()
        register_project(project, proj_raw)
        projects.add(project)
        verdict = (data.get("verdict") or "?").strip()
        verdict_counts[verdict] += 1
        mode = data.get("mode") or "?"
        findings = data.get("findings") or []

        finding_personas = set()
        for f in findings:
            for p in (f.get("personas") or []):
                finding_personas.add(canon_persona(p, amap))
        participants = {canon_persona(p, amap) for p in (data.get("personas_run") or [])} | finding_personas
        for p in participants:
            pruns[p] += 1

        for f in findings:
            sev = (f.get("severity") or "noted").lower()
            if sev not in SEV:
                sev = "noted"
            sev_totals[sev] += 1
            ps = list(dict.fromkeys(canon_persona(p, amap) for p in (f.get("personas") or [])))
            ev = f.get("evidence")
            fid = f.get("id")
            d_entry = dispmap.get(fid) if fid else None
            d_val = d_entry.get("disposition") if isinstance(d_entry, dict) else None
            if d_val == "no-record":
                d_val = None  # skeleton placeholder = untriaged, not disposed
            if sev == "critical":
                criticals.append((date, project, f.get("title") or "(untitled)", ",".join(ps)))
            # Machine verification signal: REFUTED counts as a false-positive source,
            # distinguished from human rejected-wrong so callers can audit each channel.
            verif = f.get("verification") if isinstance(f, dict) else None
            machine_refuted = (isinstance(verif, dict) and verif.get("verdict") == "REFUTED")
            sev_op = verif.get("severity_opinion") if isinstance(verif, dict) else None
            for p in ps:
                pfind[p] += 1
                psev[p][sev] += 1
                if ev:
                    pev[p] += 1
                    if ev in ("cited-spec", "code-site"):
                        pcited[p] += 1
                # Score a finding as a false positive at most once and only
                # against a denominator that includes it. Human disposition takes
                # precedence over machine refutation. REFUTED verdicts carry no
                # severity opinion because no defect mechanism was established.
                if sev_op in ("agree", "too-high", "too-low") and not machine_refuted:
                    psev_op[p][sev_op] += 1
                if machine_refuted:
                    pfp_machine[p] += 1          # visibility only; never scored directly
                if d_val:
                    pdisp[p] += 1
                    if d_val == "rejected-wrong":
                        pfp[p] += 1
                        pfp_human[p] += 1
                elif machine_refuted:
                    # No human ruling: the machine verdict adjudicates, and must
                    # land in the denominator it is being scored against.
                    pdisp[p] += 1
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
                    nm = canon_persona(nm, amap)
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
                    "human_false_positives": pfp_human[p],
                    "machine_false_positives": pfp_machine[p],
                    "severity_opinions": dict(psev_op[p]),
                    "tokens": ptokens[p] if ptoken_runs[p] else None,
                    "tokens_runs": ptoken_runs[p],
                } for p in personas
            },
            "portfolio": {
                "runs": parsed, "projects": sorted(project_display.get(k, k) for k in projects),
                "severity_totals": dict(sev_totals), "verdicts": dict(verdict_counts),
                "criticals": [
                    {"date": dt, "project": project_display.get(pr, pr), "title": ti, "personas": pe}
                    for dt, pr, ti, pe in criticals
                ],
                "overlap_important_plus": [
                    {"pair": [a, b], "count": c} for c, a, b in pairs
                ],
            },
            "runs": [{**r, "project": project_display.get(r["project"], r["project"])} for r in runs_meta],
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

    # Severity accuracy — the third number SKILL.md §9 has always promised and
    # never been able to compute. Silent until verdicts carrying the field accrue.
    sev_tot = defaultdict(int)
    for p in psev_op:
        for k, v in psev_op[p].items():
            sev_tot[k] += v
    n_op = sum(sev_tot.values())
    if n_op:
        agree = sev_tot.get("agree", 0)
        hi, lo = sev_tot.get("too-high", 0), sev_tot.get("too-low", 0)
        L.append("## Severity accuracy")
        L.append("")
        L.append(f"**{100*agree/n_op:.0f}% agree** across {n_op} CONFIRMED/PLAUSIBLE verdicts "
                 f"carrying a `severity_opinion` — {hi} filed too high, {lo} filed too low. "
                 f"Skew {'high' if hi > lo else 'low' if lo > hi else 'balanced'}"
                 f"{f' ({hi}:{lo})' if hi != lo else ''}. "
                 "REFUTED verdicts are excluded by contract (no established mechanism to "
                 "judge the filed tier against), as are verdicts written before 2026-08-09.")
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
            pr = project_display.get(pr, pr)
            ti = (ti.replace("|", "\\|").replace("`", "'")
                    .replace("[", "\\[").replace("]", "\\]").replace("\n", " "))
            pr = pr.replace("|", "\\|").replace("\n", " ")
            L.append(f"| {dt} | {pr} | {ti} | {pe} |")
        L.append("")

    print("\n".join(L))


if __name__ == "__main__":
    main()
