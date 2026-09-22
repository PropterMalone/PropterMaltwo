#!/usr/bin/env bash
# md2html.sh — render a Markdown file to a self-contained, styled HTML page.
#
# House stylesheet lives in ~/.claude/templates/doc.css; edit it there, not
# per-document. Output is standalone (CSS inlined), light/dark aware,
# print-clean, with horizontally-scrolling tables.
#
# Usage:
#   md2html.sh <input.md> [output.html]
#
# With no output path, writes alongside the input (same basename, .html).
# Prints the output path on stdout so callers can chain into whatever serves
# the file (the /push skill pipes it into serve-to-workstation.sh).
#
# Why a script and not a skill: the conversion is deterministic and costs zero
# model tokens. Hand-authoring the HTML costs ~9k output tokens per document
# and drifts in style between documents.
#
# Requires: pandoc (apt install pandoc / brew install pandoc) and python3.

set -euo pipefail

CSS="${MD2HTML_CSS:-$HOME/.claude/templates/doc.css}"

die() { echo "ERROR: $*" >&2; exit 1; }

[ $# -ge 1 ] || die "usage: md2html.sh <input.md> [output.html]"

IN="$1"
[ -f "$IN" ] || die "no such file: $IN"
command -v pandoc >/dev/null 2>&1 || die "pandoc not installed (apt install pandoc)"
[ -f "$CSS" ] || die "missing stylesheet: $CSS (override with MD2HTML_CSS)"

if [ $# -ge 2 ]; then
  OUT="$2"
else
  OUT="${IN%.*}.html"
fi

# Title: first ATX H1 if present, else the basename. Strip markdown emphasis
# and inline code marks so the browser tab reads cleanly.
TITLE="$(grep -m1 '^# ' "$IN" 2>/dev/null | sed -e 's/^# *//' -e 's/[*_`]//g' || true)"
[ -n "$TITLE" ] || TITLE="$(basename "${IN%.*}")"

# tex_math_dollars is OFF below: pandoc's gfm reader treats $...$ as inline math, so a
# doc with two prices in one sentence loses BOTH and everything between them. It warns
# only when the span fails to parse as TeX, so the usual case is silent. Caught when a
# memo full of dollar figures rendered with every one of them missing.
pandoc "$IN" \
  --standalone \
  --embed-resources \
  --from=gfm+footnotes+definition_lists-tex_math_dollars \
  --to=html5 \
  --css="$CSS" \
  --metadata title="$TITLE" \
  --wrap=preserve \
  --output="$OUT"

# pandoc renders --metadata title into a <header id="title-block-header"> AND
# the document's own leading "# Title" stays in the body — a duplicated heading.
# Drop the generated block when the source already opens with an H1.
if grep -q '^# ' "$IN" 2>/dev/null; then
  python3 - "$OUT" <<'PY'
import re, sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
s2 = re.sub(r'<header id="title-block-header">.*?</header>\n?', '', s, flags=re.S)
if s2 != s:
    open(p, "w", encoding="utf-8").write(s2)
PY
fi

echo "$OUT"
