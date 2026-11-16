#!/usr/bin/env bash
# Pelita funds. `status [--json]`: deployer, Keeper, Tank and ward balances (read-only).
# `tukar <eth>`: swap Base Sepolia ETH for lREACT through the faucet contract `request(address)` (first try 0.01).
# Key: Foundry keystore `pelita` + ~/.config/pelita/keystore.pass; RPC overrides PELITA_RPC_<CHAIN>.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$here/lib/funds.py" "$@"
