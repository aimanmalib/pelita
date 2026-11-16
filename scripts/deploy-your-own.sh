#!/usr/bin/env bash
# Run your own Pelita: one command, your own Foundry keystore. Deploys a Keeper on Reactive Lasna and a Tank on
# Base Sepolia (no demo contracts), funds both by plain transfer to the amounts in config/pelita.json `funds`,
# and writes deployments/own/<chain>.json. Foundry asks for your keystore password.
#
#   scripts/deploy-your-own.sh <keystore-name>        # a name from `cast wallet list`
#
# Then protect a contract you own (Lasna example; amounts in wei):
#   cast send <keeper> "protect(uint256,address,uint256,uint256,uint32)" 5318007 <your-contract> \
#     50000000000000000 100000000000000000 10 --account <keystore-name> --rpc-url https://lasna-rpc.rnk.dev/
set -euo pipefail
if [ $# -lt 1 ] || [ "${1#-}" != "$1" ]; then
  echo "usage: $0 <keystore-name> [--no-verify]" >&2
  exit 2
fi
name="$1"; shift
here="$(cd "$(dirname "$0")" && pwd)"
export PELITA_ACCOUNT="$name"
export PELITA_PASSWORD_FILE="${PELITA_PASSWORD_FILE:-}"
unset PELITA_KEYSTORE
exec python3 "$here/lib/deployer.py" --no-demo --out "$here/../deployments/own" "$@"
