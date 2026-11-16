#!/usr/bin/env bash
# Re-reads every chain fact in config/chains.json from the chains (no key, no transaction)
# and writes docs/evidence/E-001-chain-facts.json. Exit 1 when an active chain disagrees with config.
set -euo pipefail
cd "$(dirname "$0")/../.."
export CAST="${CAST:-$HOME/.foundry/bin/cast}"
exec python3 scripts/spike/chain_facts.py "$@"
