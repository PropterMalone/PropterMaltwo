#!/usr/bin/env bash
# Drop Knip + Fallow + a `lint:dead` gate into a TypeScript project's validate chain.
#
# CLAUDE.md's Tech Stack section names `lint:dead` as part of `npm run validate`;
# this is the script that wires it in. SETUP.md calls it for new projects, and it
# is idempotent, so you can also run it on an existing project to add the gate
# after the fact.
#
# Usage: cd <project-root> && ~/.claude/scripts/setup-knip-fallow.sh
#
# adapt: knip and fallow are one pairing (unused exports/files, and dead code +
# duplication respectively). Swap in whatever dead-code tooling your stack has —
# what matters is that ONE command fails the build when dead code accumulates,
# rather than a report nobody reads.
set -euo pipefail

if [[ ! -f package.json ]]; then
  echo "error: no package.json in $(pwd). Run from a TS project root." >&2
  exit 1
fi

echo "==> Installing knip + fallow as devDeps"
npm i -D knip fallow

echo "==> Writing minimal knip.json (if absent)"
if [[ ! -f knip.json ]]; then
  cat > knip.json <<'EOF'
{
  "$schema": "https://unpkg.com/knip@6/schema.json",
  "ignoreExportsUsedInFile": true,
  "rules": {
    "types": "warn",
    "classMembers": "warn",
    "duplicates": "warn"
  }
}
EOF
fi

echo "==> Writing minimal .fallowrc.json (if absent)"
if [[ ! -f .fallowrc.json ]]; then
  cat > .fallowrc.json <<'EOF'
{
  "entry": ["src/**/*.ts", "src/**/*.tsx", "src/**/*.test.ts"],
  "ignorePatterns": ["dist/**", "build/**", "node_modules/**", "**/__mocks__/**"],
  "rules": {
    "unused-types": "warn",
    "duplicate-exports": "warn",
    "complexity": "warn",
    "duplication": "warn",
    "unresolved-imports": "warn"
  }
}
EOF
fi

echo "==> Wiring lint:dead scripts in package.json"
node <<'EOF'
const fs = require('fs');
const raw = fs.readFileSync('package.json', 'utf8');
const pkg = JSON.parse(raw);
// Detect existing indent so we don't fight tab-conventioned projects.
const indentMatch = raw.match(/\n([ \t]+)"/);
const indent = indentMatch ? indentMatch[1] : 2;
pkg.scripts ??= {};
pkg.scripts['lint:dead'] = pkg.scripts['lint:dead'] ?? 'knip && fallow dead-code';
pkg.scripts['lint:dead:full'] = pkg.scripts['lint:dead:full'] ?? 'knip && fallow';
// Best-effort: append to validate if it exists and doesn't already include lint:dead
if (pkg.scripts.validate && !pkg.scripts.validate.includes('lint:dead')) {
  pkg.scripts.validate = pkg.scripts.validate + ' && npm run lint:dead';
}
fs.writeFileSync('package.json', JSON.stringify(pkg, null, indent) + '\n');
console.log('package.json scripts updated (indent: ' + JSON.stringify(indent) + ')');
EOF

echo
echo "==> Running first lint:dead to surface findings"
if npm run lint:dead 2>&1; then
  echo "==> Clean. Wire it into your CI if desired."
else
  echo
  echo "==> Findings above. Triage each one as SAFE-TO-FIX / NEEDS-JUDGMENT /"
  echo "    FALSE-POSITIVE before changing anything. The first sweep on an"
  echo "    existing project is mostly false positives (dynamic imports, entry"
  echo "    points the config doesn't know about); tune the config, don't delete"
  echo "    code to make the tool quiet."
fi
