#!/usr/bin/env bash
# Runs test/fork/* against live Lasna and Base Sepolia forks (read only: nothing is broadcast).
# Picks a Lasna contract that is dark right now: the newest BlacklistContract target with debt > 0.
# Not part of CI or scripts/gerbang-ujian.sh; results are copied into docs/test-results.md by hand.
set -euo pipefail
cd "$(dirname "$0")/../.."
FOUNDRY_BIN="${FOUNDRY_BIN:-$HOME/.foundry/bin}"
read -r LASNA_RPC BASE_RPC BILLER SPAN TOPIC < <(python3 -c '
import json; c=json.load(open("config/chains.json")); l=c["chains"]["lasna"]
print(l["rpc"], c["chains"]["base-sepolia"]["rpc"], l["biller"], l["get_logs_max_blocks"], c["topics"]["BlacklistContract(address)"])')

target="${PELITA_DARK_TARGET:-}"
if [ -z "$target" ]; then
  top=$("$FOUNDRY_BIN/cast" block-number --rpc-url "$LASNA_RPC")
  for i in 0 1 2 3; do
    hi=$((top - i * SPAN)); lo=$((hi - SPAN + 1))
    for t in $("$FOUNDRY_BIN/cast" logs --rpc-url "$LASNA_RPC" --address "$BILLER" --from-block "$lo" --to-block "$hi" "$TOPIC" --json |
      python3 -c 'import json,sys; [print("0x"+l["topics"][1][-40:]) for l in reversed(json.load(sys.stdin))]'); do
      debt=$("$FOUNDRY_BIN/cast" call "$BILLER" 'debt(address)(uint256)' "$t" --rpc-url "$LASNA_RPC" | cut -d' ' -f1)
      if [ "$debt" != "0" ]; then target="$t"; break 2; fi
    done
  done
fi
[ -n "$target" ] || { echo "fork-tests: no dark contract found in the newest windows" >&2; exit 2; }
echo "fork-tests: dark target $target"
PELITA_FORK_RPC="$LASNA_RPC" PELITA_FORK_RPC_BASE="$BASE_RPC" PELITA_DARK_TARGET="$target" \
  "$FOUNDRY_BIN/forge" test --match-path 'test/fork/*' "$@"
