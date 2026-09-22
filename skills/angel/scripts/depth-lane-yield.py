#!/usr/bin/env python3
# pattern: imperative shell
"""ADR-19 falsifier for depth-lane Important+ yield after a model-tier change.

The instrument uses a paired within-run yield ratio so project difficulty, diff size,
and contemporaneous conditions are shared by the depth and control arms:

    R = (Important+ attributions per DEPTH-arm persona) / (per CONTROL-arm persona)

Month breakdowns remain visible because prompt and roster evolution can create strong
era effects. `test` is excluded because it follows a different tier transition, which
would conflate two separate decisions under one threshold. Alternative metrics based on
pass reproducibility, evidence-tier share, or solo-finding share are unsuitable because
of quantization or denominator bias.

Usage: depth-lane-yield.py [--runs-dir DIR] [--backward] [--json]
"""
import argparse
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # runs as __main__ from any CWD
from angel_corpus import in_scope, load_snapshot, run_date
from persona_aliases import build_persona_aliases, canon_persona

SKILL_DIR = Path(__file__).resolve().parent.parent

# Pre-registered constants. See ADR-19 for the derivation of each; changing a value here
# without amending the ADR breaks the pre-registration these numbers exist to provide.
DEPTH_ARM = ("thousand", "data-int", "future", "blindspot", "coach",
             "rigor", "deanon", "heir", "recip")
CONTROL_ARM = ("adv", "hyper", "user", "perf", "install", "penny",
               "rtfm", "editor", "orgpolicy", "naive", "fresh", "pii")
_EXCLUDED = ("test",)             # moves to Sonnet, not Opus — a different bet
# Derived so moving a persona into _EXCLUDED changes behavior; absence from both arm
# tuples alone is not a sufficient exclusion mechanism.
DEPTH_ARM = tuple(p for p in DEPTH_ARM if p not in _EXCLUDED)
CONTROL_ARM = tuple(p for p in CONTROL_ARM if p not in _EXCLUDED)
EXCLUDED = _EXCLUDED

# Families that are Claude-side. The ADR-18 codex backend is deliberately NOT one: its
# legs are review signal, but they are not evidence about which Claude tier a run used.
CLAUDE_FAMILIES = ("fable", "opus", "sonnet", "haiku")
# The two tiers actually under comparison. A depth persona running Sonnet (the standard
# profile demotes `future`) is on a control-tier model and is excluded from the depth arm
# for that run rather than being counted as depth yield.
DEPTH_TIERS = ("fable", "opus")

RETIREMENT_DATE = "2026-08-26"    # ADR-19; also the ADR-18 trial partition marker
BASELINE_FLOOR = "2026-07-08"     # ADR-07's date — the era the baseline is drawn from
BASELINE_MEDIAN = 2.82            # pre-registered reference used by the decision rule
BASELINE_N = 20                   # minimum reference sample encoded by the protocol
THRESHOLD_R = 1.69                # pre-registered decision threshold
MIN_POST_RUNS = 10

# Arm guards. A run with a thin control arm produces a ratio dominated by one persona's
# luck on one diff; it is excluded rather than allowed to move a median.
MIN_CONTROL_PERSONAS = 3
MIN_CONTROL_IMPPLUS = 4
MIN_DEPTH_PERSONAS = 2

IMPPLUS = ("critical", "important")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def persona_legs(run_dir, amap):
    """-> {canonical persona: [ {model, backend, note}, ... ] } — ONE ENTRY PER USAGE LINE.

    Not a set. A set collapses two Claude passes on the same model into one vote, which
    silently defeated the N=3 escalation: pass 1 + pass 3 on Opus deduped to a single
    `opus` element against the codex pass's one, giving a 1:1 tie where the run actually
    dispatched 2:1. Legs are the unit the ballot claims to count, so legs are what is kept.

    The arm a run lands in is decided by the model that ACTUALLY ran, not by the date —
    so lapse-ladder substitutions and `--model-override` runs self-sort instead of being
    mis-attributed to whatever the table said that week. `note` is carried because the
    usage schema records the REQUESTED model in `model` and any contradiction in `note`
    (`requested=…|ran=…`, MODEL_MISMATCH, FAILED); a leg whose note reports a mismatch or
    a failure is not evidence that the requested model ran.
    """
    out = defaultdict(list)
    p = run_dir / "usage.jsonl"
    if not p.is_file():
        return out
    for line in p.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if not isinstance(rec, dict) or rec.get("phase") != "persona":
            continue
        model = (rec.get("model") or "").strip()
        if not model:
            continue
        out[canon_persona(rec.get("name"), amap)].append({
            "model": model,
            "backend": (rec.get("backend") or "").strip().lower(),
            "note": (rec.get("note") or "").strip(),
        })
    return out


def leg_is_usable(leg):
    """A leg counts toward the ballot only when it is Claude-side and not known-bad.

    `backend: codex` is set by dispatch-leg.sh on every ADR-18 pass-2 leg. Counting those
    is what made every heterogeneous run unattributable: each depth persona cast one
    Claude vote and one codex vote, purity landed at exactly 0.5, the strict majority
    test failed, and the run left both arms. The discriminator was already in the log.
    """
    if leg["backend"] == "codex":
        return False
    note = leg["note"].upper()
    if "MODEL_MISMATCH" in note or "FAILED" in note:
        return False
    return family(leg["model"]) in CLAUDE_FAMILIES


def family(model_id):
    """-> 'fable' | 'opus' | 'sonnet' | 'haiku' | 'other' for one model string."""
    low = (model_id or "").lower()
    for fam in ("fable", "opus", "sonnet", "haiku"):
        if fam in low:
            return fam
    return "other"


def depth_tier_legs(legs_by_persona, persona):
    """-> the usable, depth-tier Claude legs a depth persona actually ran."""
    return [family(l["model"]) for l in legs_by_persona.get(persona) or []
            if leg_is_usable(l) and family(l["model"]) in DEPTH_TIERS]


def attribute(legs_by_persona, depth_ran):
    """-> (arm, purity) by LEG-LEVEL MAJORITY over usable depth-tier Claude legs.

    Not unanimity. Under the lapse ladder a run routinely had `data-int` on Fable while
    `rigor` had demoted to Opus, and requiring one family throws away most of the corpus.
    A run is attributed to the family running a strict majority of those legs, and
    `purity` is reported so a 6/11 attribution is never mistaken for a clean one.

    Codex legs do not vote. They are excluded before counting, not after: under ADR-18
    every persona has one, so counting them put every heterogeneous run at exactly 0.5
    purity and out of both arms — the defect that made this instrument's forward arm
    unable to populate at all, found by its own first review.
    """
    legs = [f for p in depth_ran for f in depth_tier_legs(legs_by_persona, p)]
    if not legs:
        return "mixed", 0.0
    dom, cnt = Counter(legs).most_common(1)[0]
    purity = cnt / len(legs)
    return (dom if purity > 0.5 else "mixed"), purity


def norm(value):
    """-> lowercased string, or None when the field is not a string.

    Snapshot fields descend from reviews of untrusted projects. A truthy non-string
    `severity` used to raise AttributeError out of the normalize expression and abort the
    ENTIRE scan — one malformed run could suppress the instrument that monitors the review
    battery. Malformed values are now quarantined per-row and reported.
    """
    return value.strip().lower() if isinstance(value, str) else None


def claude_sourced(finding, persona):
    """Did THIS persona's Claude pass find this finding?

    R compares a Claude tier against a Claude tier. Under ADR-18 a persona's codex pass
    is credited to the same persona name, so without this every post-retirement run
    counted a second model's findings as the first model's — inflating the depth arm on
    one reading and the control arm on another, and in both cases measuring something
    other than the variable ADR-19 names.

    Absent `backend_support` the finding predates the field, and pre-ADR-18 runs had no
    codex pass at all — so every attribution really was Claude-sourced and counting it is
    correct, not a guess.
    """
    bs = finding.get("backend_support")
    if not isinstance(bs, dict):
        return True
    counts = bs.get(persona)
    if not isinstance(counts, dict):
        return True
    return counts.get("claude", 0) > 0


def run_ratio(data, legs_by_persona, amap, issues):
    """-> (row, None) with R and the arm counts, or (None, reason) when guards reject."""
    depth_hits, ctl_hits = Counter(), Counter()
    for f in data.get("findings") or []:
        if not isinstance(f, dict):
            issues.append("finding is not an object")
            continue
        sev = norm(f.get("severity"))
        if sev is None:
            issues.append(f"non-string severity: {f.get('severity')!r}")
            continue
        if sev not in IMPPLUS:
            continue
        personas = f.get("personas")
        if not isinstance(personas, list):
            issues.append(f"personas not a list on {f.get('id')!r}")
            continue
        seen = set()
        for raw in personas:
            if not isinstance(raw, str):
                issues.append(f"non-string persona on {f.get('id')!r}: {raw!r}")
                continue
            p = canon_persona(raw, amap)
            if p in seen:
                continue
            seen.add(p)
            if not claude_sourced(f, p):
                continue          # a codex-only catch is review signal, not Claude-tier yield
            if p in DEPTH_ARM:
                depth_hits[p] += 1
            elif p in CONTROL_ARM:
                ctl_hits[p] += 1

    # Arm membership is decided PER RUN from the model each persona actually ran, not from
    # the static tuple. The standard profile demotes `future` to Sonnet, so on most runs it
    # is a depth-arm NAME running a control-tier MODEL; counting it as depth yield mixes a
    # Sonnet lane into a metric whose whole subject is the depth tier.
    depth_ran = {p for p in DEPTH_ARM if depth_tier_legs(legs_by_persona, p)}
    ctl_ran = {p for p in CONTROL_ARM
               if any(leg_is_usable(l) for l in legs_by_persona.get(p) or [])}
    degraded = False
    if not depth_ran:
        # No usable depth-tier model evidence. Fall back to scorers so the run stays
        # measurable, but SAY SO: `degraded` used to be computed from whether the WHOLE
        # persona dict was empty, so a usage.jsonl carrying control legs but missing depth
        # legs fell back to scorers silently while reporting itself clean.
        depth_ran = set(depth_hits)
        ctl_ran = ctl_ran or set(ctl_hits)
        degraded = True

    if len(ctl_ran) < MIN_CONTROL_PERSONAS:
        return None, "control arm below MIN_CONTROL_PERSONAS"
    if sum(ctl_hits.values()) < MIN_CONTROL_IMPPLUS:
        return None, "control arm below MIN_CONTROL_IMPPLUS"
    if len(depth_ran) < MIN_DEPTH_PERSONAS:
        return None, "depth arm below MIN_DEPTH_PERSONAS"

    depth_rate = sum(depth_hits.values()) / len(depth_ran)
    ctl_rate = sum(ctl_hits.values()) / len(ctl_ran)
    if ctl_rate == 0:
        return None, "control arm scored zero Important+"
    arm, purity = attribute(legs_by_persona, depth_ran)
    return {
        "R": depth_rate / ctl_rate,
        "depth_impplus": sum(depth_hits.values()), "depth_personas": len(depth_ran),
        "control_impplus": sum(ctl_hits.values()), "control_personas": len(ctl_ran),
        "depth_arm": arm, "depth_purity": round(purity, 2),
        "degraded": degraded,
    }, None


def scan(runs_dir, amap):
    """Every directory iterated lands in exactly one bucket. Nothing vanishes.

    Before ADR-19's own review this dropped two whole populations in silence: a run dir
    with no snapshot candidate at all (44% of the corpus) and a run rejected by the arm
    guards (another 75). Combined, two thirds of the corpus never appeared in any output,
    while the report's "guarded runs scanned" line implied that WAS the corpus.
    """
    rows, unreadable, reduced, no_snapshot, issues = [], [], [], [], []
    guard_rejects = Counter()
    scanned = 0
    for rd in sorted(d for d in runs_dir.iterdir() if d.is_dir()):
        scanned += 1
        data, _name, errors = load_snapshot(rd)
        # `load_snapshot` reports BOTH failure kinds through one channel, so split them
        # here or the same file is counted twice. A snapshot that parses but carries no
        # `findings` list is a REDUCED shape (the codex runs emit `criticals`-only), not
        # a corrupt one — reduced is a schema problem that will spread, unreadable is a
        # one-off.
        for pth, why in errors:
            if why == "no `findings` list":
                reduced.append(rd.name)
            else:
                unreadable.append((str(pth), why))
        if data is None:
            if not errors:
                no_snapshot.append(rd.name)
            continue
        row, reject = run_ratio(data, persona_legs(rd, amap), amap, issues)
        if row is None:
            guard_rejects[reject] += 1
            continue
        row.update(run=rd.name, date=run_date(data, rd),
                   project=(data.get("project") or "?").strip().lower())
        rows.append(row)
    accounted = len(rows) + len(reduced) + len(unreadable) + len(no_snapshot) + sum(guard_rejects.values())
    return {
        "rows": rows, "unreadable": unreadable, "reduced": reduced,
        "no_snapshot": no_snapshot, "guard_rejects": dict(guard_rejects),
        "data_issues": issues, "dirs_scanned": scanned, "dirs_accounted": accounted,
    }


def describe(rows):
    if not rows:
        return None
    rs = sorted(r["R"] for r in rows)
    months = defaultdict(list)
    for r in rows:                       # group ONCE; by_month and by_month_n both derive
        months[r["date"][:7]].append(r["R"])
    return {
        "n": len(rs), "median": statistics.median(rs), "min": rs[0], "max": rs[-1],
        "projects": len({r["project"] for r in rows}),
        "by_month": {m: round(statistics.median(v), 2) for m, v in sorted(months.items())},
        "by_month_n": {m: len(v) for m, v in sorted(months.items())},
    }


def fire_probability(baseline, s, threshold, n):
    """P(median of n runs < threshold) when the true effect retains fraction `s` of baseline.

    Exact, not simulated: each run is an iid draw from the baseline distribution scaled by
    s, so p = P(one run < threshold) is a fraction of the empirical baseline, and the
    median of n falls below the bar iff at least ceil(n/2) draws do — a binomial tail.

    This exists because ADR-19 originally shipped three fire probabilities (~3%/~46%/~94%)
    with no reproducing code, in a document whose own test suite forbids exactly that. The
    precedent it invoked (ADR-16's ~49%) IS instrument-computed. Now this one is too.
    """
    if not baseline or s <= 0:
        return None
    scaled = [v * s for v in baseline]
    p = sum(1 for v in scaled if v < threshold) / len(scaled)
    need = (n + 1) // 2 if n % 2 else n // 2 + 1     # strict majority below the bar
    return sum(math.comb(n, k) * p ** k * (1 - p) ** (n - k) for k in range(need, n + 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-dir", default=str(Path.home() / ".angel" / "runs"))
    ap.add_argument("--backward", action="store_true",
                    help="evaluate the pre-retirement Fable arm as if it were the post arm "
                         "(the ADR-14 backward run: proves the threshold discriminates)")
    ap.add_argument("--json", action="store_true", help="emit machine JSON instead of a report")
    args = ap.parse_args()

    runs_dir = Path(args.runs_dir)
    if not runs_dir.is_dir():
        print(f"no runs dir: {runs_dir}", file=sys.stderr)
        sys.exit(1)

    amap = build_persona_aliases(SKILL_DIR)
    sc = scan(runs_dir, amap)
    rows = sc["rows"]

    if args.backward:
        # Bounded ABOVE as well as below. `fable` is still a legal --model-override, so an
        # open-ended floor would let a post-retirement Fable run join a population labelled
        # "pre-retirement" and silently diverge the arm from the registered baseline.
        arm = [r for r in rows if r["depth_arm"] == "fable"
               and in_scope(r["date"], BASELINE_FLOOR) and r["date"] < RETIREMENT_DATE]
        label = f"BACKWARD — Fable arm, {BASELINE_FLOOR} .. {RETIREMENT_DATE} (exclusive)"
    else:
        arm = [r for r in rows if r["depth_arm"] == "opus"
               and in_scope(r["date"], RETIREMENT_DATE)]
        label = f"FORWARD — Opus arm since {RETIREMENT_DATE} (ADR-19)"

    stats = describe(arm)
    have = stats["n"] if stats else 0
    powered = have >= MIN_POST_RUNS
    med = stats["median"] if stats else None
    fired = bool(powered and med is not None and med < THRESHOLD_R)
    verdict = "FIRED" if fired else ("not met" if powered else f"pending ({have}/{MIN_POST_RUNS} runs)")

    baseline_vals = sorted(r["R"] for r in rows if r["depth_arm"] == "fable"
                           and in_scope(r["date"], BASELINE_FLOOR) and r["date"] < RETIREMENT_DATE)
    sharpness = {f"retain_{int(s*100)}pct": fire_probability(baseline_vals, s, THRESHOLD_R, MIN_POST_RUNS)
                 for s in (1.0, 0.80, 0.70, 0.60, 0.50)}

    result = {
        "mode": "backward" if args.backward else "forward",
        "threshold_r": THRESHOLD_R, "min_runs": MIN_POST_RUNS,
        "baseline": {"median": BASELINE_MEDIAN, "n": BASELINE_N, "floor": BASELINE_FLOOR,
                     "ceiling": RETIREMENT_DATE},
        "arm": stats, "runs": arm,
        "runs_below_threshold": sum(1 for r in arm if r["R"] < THRESHOLD_R),
        "arm_census": dict(Counter(r["depth_arm"] for r in rows)),
        "runs_degraded": sum(1 for r in rows if r["degraded"]),
        "corpus": {
            "dirs_scanned": sc["dirs_scanned"], "dirs_accounted": sc["dirs_accounted"],
            "measured": len(rows), "no_snapshot": len(sc["no_snapshot"]),
            "reduced_shape": len(sc["reduced"]), "unreadable": len(sc["unreadable"]),
            "guard_rejected": sc["guard_rejects"],
        },
        "data_issues": sc["data_issues"][:20],
        "fire_probability_at_min_runs": sharpness,
        "reference_arms": {a: describe([r for r in rows if r["depth_arm"] == a])
                           for a in ("fable", "opus", "sonnet", "haiku", "other", "mixed")
                           if any(r["depth_arm"] == a for r in rows)},
        "clauses": {"powered": powered,
                    "below_threshold": bool(med is not None and med < THRESHOLD_R)},
        "verdict": verdict,
    }
    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    c = result["corpus"]
    print("ADR-19 falsifier — depth-lane Important+ yield vs the unmoved control arm")
    print(f"  {label}")
    print(f"  corpus: {c['dirs_scanned']} dirs scanned, {c['dirs_accounted']} accounted "
          f"({'balanced' if c['dirs_scanned'] == c['dirs_accounted'] else 'MISMATCH'})")
    print(f"    measured {c['measured']}  |  no snapshot {c['no_snapshot']}  |  "
          f"reduced-shape {c['reduced_shape']}  |  unreadable {c['unreadable']}")
    for why, k in sorted(c["guard_rejected"].items()):
        print(f"    guard-rejected {k:>3}  — {why}")
    if result["runs_degraded"]:
        print(f"    !! {result['runs_degraded']} run(s) had no usable depth-tier model evidence "
              f"(scorer fallback)")
    if sc["data_issues"]:
        print(f"    !! {len(sc['data_issues'])} malformed field(s) quarantined: {sc['data_issues'][0]}")
    print(f"  arm census: " + ", ".join(f"{k}={v}" for k, v in sorted(result["arm_census"].items())))
    print()
    if not stats:
        print("  arm is empty — nothing to measure yet.")
    else:
        print(f"  n = {stats['n']} runs across {stats['projects']} projects")
        print(f"  median R = {stats['median']:.2f}   (min {stats['min']:.2f}, max {stats['max']:.2f})")
        print(f"  runs individually below {THRESHOLD_R}: {result['runs_below_threshold']} of {stats['n']}")
        print()
        print("  by month (era is this instrument's dominant nuisance — pooling hides it):")
        for m, v in stats["by_month"].items():
            print(f"    {m}   n={stats['by_month_n'][m]:>2}   median R = {v:.2f}")
    print()
    print("  reference arms, all time — read the month columns, not the pooled medians:")
    for a, st in result["reference_arms"].items():
        months = "  ".join(f"{m}:{v:.2f}" for m, v in st["by_month"].items())
        print(f"    {a:6} n={st['n']:>3}  pooled median R={st['median']:.2f}   by month  {months}")
    print("    (a 3x swing within one arm on an unchanged model is era, not model.)")
    print()
    print(f"  sharpness — P(fires at n={MIN_POST_RUNS}) if the true effect retains:")
    for k, v in sharpness.items():
        if v is not None:
            print(f"    {k.replace('retain_','').replace('pct','')}% of baseline yield : {v*100:5.1f}%")
    print()
    print(f"  baseline (Fable arm, {BASELINE_FLOOR} .. {RETIREMENT_DATE}): "
          f"median {BASELINE_MEDIAN} on n={BASELINE_N}")
    print(f"  [{'x' if result['clauses']['powered'] else ' '}] powered          n >= {MIN_POST_RUNS}  (have {have})")
    print(f"  [{'x' if result['clauses']['below_threshold'] else ' '}] below threshold  median R < {THRESHOLD_R}")
    print()
    print(verdict)
    return 0


if __name__ == "__main__":
    sys.exit(main())
