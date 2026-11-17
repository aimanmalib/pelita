#!/usr/bin/env bash
# Offline test gate: Solidity format, build, unit tests (fork tests excluded), Python tests and README links.
# Foundry is called by absolute path because cron and non-interactive shells do not load it into PATH.
set -euo pipefail
cd "$(dirname "$0")/.."
FOUNDRY_BIN="${FOUNDRY_BIN:-$HOME/.foundry/bin}"
forge="$FOUNDRY_BIN/forge"
[ -x "$forge" ] || forge="$(command -v forge)"

for f in scripts/*.sh scripts/spike/*.sh deploy/*.sh; do bash -n "$f"; done
"$forge" fmt --check
"$forge" build --quiet
"$forge" test --no-match-path 'test/fork/*' -q 2>&1 | tail -n 5
python3 -m unittest discover -s tests -t . -q
python3 scripts/check-links.py
echo "gerbang-ujian: OK"
