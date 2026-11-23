#!/usr/bin/env bash
# Deploys Pelita to the active chains in config/chains.json (Reactive Lasna + Base Sepolia). Idempotent: a second run
# sends no transaction. Order: Keeper (reactive) -> Tank (callback, needs the Keeper address) -> setChain -> demo
# Beacon/Flicker/Lantern pairs (guarded + control) -> protect the guarded pair -> fund Keeper and Tank by plain
# transfer -> source verification (Sourcify on Lasna, Blockscout on Base Sepolia). Writes deployments/<chain>.json.
#
# Key: Foundry keystore `pelita` + ~/.config/pelita/keystore.pass (PELITA_ACCOUNT / PELITA_KEYSTORE /
# PELITA_PASSWORD_FILE override). RPC: PELITA_RPC_LASNA / PELITA_RPC_BASE_SEPOLIA override config.
# Options: --no-verify  --no-demo  --verify-only (no transaction)  --out <dir>
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$here/lib/deployer.py" "$@"
