#!/usr/bin/env bash
# Check Pelita on-chain without trusting the README. Read-only: plain `cast` calls, no key.
# Every command is printed before it runs, so you can copy it. Addresses come from deployments/<chain>.json.
#   scripts/verify.sh [deployments-dir]
# RPC overrides: PELITA_RPC_LASNA / PELITA_RPC_BASE_SEPOLIA. Exit 1 if a recorded contract has no code.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
dir="${1:-$root/deployments}"
cast="${FOUNDRY_BIN:-$HOME/.foundry/bin}/cast"
[ -x "$cast" ] || cast="$(command -v cast)"

# One line per fact: chain|rpc|biller|chain_id|kind|address|role
facts() {
  python3 - "$root/config/chains.json" "$dir" <<'PY'
import json, os, sys
chains = json.load(open(sys.argv[1]))["chains"]
for name, c in chains.items():
    p = os.path.join(sys.argv[2], f"{name}.json")
    if not c.get("aktif") or not os.path.exists(p):
        continue
    d = json.load(open(p))
    rpc = os.environ.get("PELITA_RPC_" + name.upper().replace("-", "_"), c["rpc"])
    base = f"{name}|{rpc}|{c['biller']}|{c['chain_id']}"
    for k in ("keeper", "tank", "beacon"):
        if d.get(k):
            print(f"{base}|{k}|{d[k]}|-")
    for w in d.get("wards", []):
        print(f"{base}|ward|{w['address']}|{w['role']}")
PY
}

run() { echo "\$ cast $*" | sed "s|--rpc-url [^ ]*|--rpc-url \$RPC|"; "$cast" "$@"; }

missing=0
keeper="" ; keeper_rpc=""
lines="$(facts)"
[ -n "$lines" ] || { echo "no deployments in $dir"; exit 1; }
while IFS='|' read -r chain rpc biller id kind addr role; do
  echo "== $chain $kind $addr ${role/-/}"
  code="$("$cast" code "$addr" --rpc-url "$rpc")"
  if [ "${#code}" -le 2 ]; then echo "   NO CODE"; missing=1; continue; fi
  echo "   code: $(( (${#code} - 2) / 2 )) bytes"
  case "$kind" in
    keeper) keeper="$addr"; keeper_rpc="$rpc"
            run call "$addr" "fuel()(uint256,uint256,uint256)" --rpc-url "$rpc"
            run call "$addr" "wardCount()(uint256)" --rpc-url "$rpc" ;;
    tank)   run balance "$addr" --ether --rpc-url "$rpc" ;;
    ward)   run call "$biller" "debt(address)(uint256)" "$addr" --rpc-url "$rpc"
            if [ -n "$keeper" ]; then
              run call "$keeper" "ward(uint256,address)((uint256,address,uint256,uint256,uint32,uint32,uint64,uint64,bool,bool))" \
                "$id" "$addr" --rpc-url "$keeper_rpc"
            fi ;;
  esac
done <<< "$lines"
exit "$missing"
