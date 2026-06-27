#!/usr/bin/env python3
# pattern: functional core
"""Pure finding-matching core for 9A cross-run / within-run analytics.

No I/O. Two scripts share this matcher:
  - recurrence-pilot.py : does a finding recur across two *runs* (replicate /
                          reader-ab / temporal pairs).
  - subsample-analyzer.py : does a finding recur across the N *passes* of one
                            multiball run (recall-vs-N + per-persona reproducibility).

Both questions reduce to "do these two finding records describe the same issue?"
— same normalized file (or basename) AND title-token overlap above a threshold.
Extracted from recurrence-pilot.py 2026-06-17 so the matcher has one definition
and one set of tests instead of being duplicated per analyzer.
"""
import re

SEV_RANK = {"critical": 3, "important": 2, "minor": 1, "noted": 0}

# Words that carry no discriminating signal in a finding title.
STOP = {
    "the", "a", "an", "is", "are", "to", "of", "in", "on", "for", "and", "or",
    "no", "not", "with", "without", "by", "from", "as", "at", "it", "its",
    "this", "that", "has", "have", "but", "via", "into", "when", "if", "can",
    "does", "do", "be", "been", "every", "any", "all", "per",
}


def norm_file(raw):
    """Path without line suffix, lowercased, leading ./ stripped. '' if absent."""
    if not raw:
        return ""
    s = str(raw).strip()
    # 'main.py:206-293' or 'main.py:206' -> 'main.py'; tolerate ':' in the tail only.
    s = re.split(r":\d", s, 1)[0]
    s = s.lstrip("./").strip().lower()
    return s


def file_match(a, b):
    """Same normalized path, or same basename (paths shift between runs)."""
    if not a or not b:
        return False
    if a == b:
        return True
    return a.rsplit("/", 1)[-1] == b.rsplit("/", 1)[-1]


def title_tokens(title):
    toks = re.findall(r"[a-z0-9]+", (title or "").lower())
    return {t for t in toks if t not in STOP and len(t) > 2}


def title_overlap(a_toks, b_toks):
    """Overlap coefficient |A&B| / min(|A|,|B|) -- robust to one title being terser."""
    if not a_toks or not b_toks:
        return 0.0
    return len(a_toks & b_toks) / min(len(a_toks), len(b_toks))


def finding_match(fa, fb, threshold):
    """fa and fb describe the same issue: same file + title-token overlap >= threshold.

    Both dicts must carry 'nfile' (normalized file) and 'toks' (title token set);
    see normalize_finding for building those from a raw snapshot entry.
    """
    if not file_match(fa["nfile"], fb["nfile"]):
        return False
    return title_overlap(fa["toks"], fb["toks"]) >= threshold


def recurs(f, others, threshold):
    """True if f matches any finding in others."""
    return any(finding_match(f, g, threshold) for g in others)


def normalize_finding(raw):
    """Raw snapshot finding dict -> matcher-ready dict (nfile/title/toks/sev).

    Accepts the snapshot 'findings' entry shape AND the within_persona_runs
    per-pass entry shape (both carry file/title/severity; line is ignored — the
    normalized file already drops the line suffix)."""
    raw_file = raw.get("file") or raw.get("location") or ""
    title = raw.get("title") or ""
    sev = (raw.get("severity") or "noted").lower()
    if sev not in SEV_RANK:
        sev = "noted"
    return {
        "nfile": norm_file(raw_file),
        "title": title,
        "toks": title_tokens(title),
        "sev": sev,
    }
