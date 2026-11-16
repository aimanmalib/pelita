"""scripts/funds.sh: balances (status) and the ETH -> lREACT faucet swap (tukar).

status  Deployer balance on every active chain, Keeper fuel() on the reactive chain, Tank balance and the debt and
        reserves of every ward from deployments/<chain>.json. Read-only (the keystore is opened only to learn the
        deployer address).
tukar   `request(address)` on the lREACT faucet contract on Base Sepolia with --value <eth>. Refuses more than
        funds.max_swap_eth (config/pelita.json) and any RPC whose chain id differs from config.
"""

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pelitarpc  # noqa: E402
from deployer import rpc_for  # noqa: E402
from foundry import WEI, Foundry, auth_from_env, to_wei  # noqa: E402


def eth(wei):
    return str((Decimal(wei) / WEI).normalize()) if wei else "0"


def _ints(text):
    return [int(line.split()[0]) for line in text.splitlines() if line.strip()]


def status(f, chains, out_dir, rpcs):
    me = f.address()
    report = {"deployer": me, "chains": {}}
    for name, chain in chains["chains"].items():
        if not chain.get("aktif"):
            continue
        rpc = rpcs[name]
        row = {"symbol": chain["native_symbol"], "deployer": eth(f.balance(rpc, me))}
        path = Path(out_dir) / f"{name}.json"
        if path.exists():
            dep = json.loads(path.read_text(encoding="utf-8"))
            if dep.get("keeper"):
                bal, res, owed = _ints(f.call(rpc, dep["keeper"], "fuel()(uint256,uint256,uint256)"))
                row["keeper"] = {"address": dep["keeper"], "balance": eth(bal), "reserves": eth(res), "owed": eth(owed)}
            if dep.get("tank"):
                row["tank"] = {"address": dep["tank"], "balance": eth(f.balance(rpc, dep["tank"]))}
            row["wards"] = [
                {
                    **w,
                    "debt": eth(_ints(f.call(rpc, chain["biller"], "debt(address)(uint256)", w["address"]))[0]),
                    "reserves": eth(_ints(f.call(rpc, chain["biller"], "reserves(address)(uint256)", w["address"]))[0]),
                }
                for w in dep.get("wards", [])
            ]
        report["chains"][name] = row
    return report


def tukar(f, chains, cfg, rpcs, amount):
    limit = Decimal(cfg["funds"]["max_swap_eth"])
    if Decimal(amount) <= 0 or Decimal(amount) > limit:
        raise ValueError(f"amount {amount} ETH outside (0, {limit}] (funds.max_swap_eth)")
    name, chain = next((n, c) for n, c in chains["chains"].items() if c.get("aktif") and c.get("lreact_faucet"))
    rpc = rpcs[name]
    got = f.chain_id(rpc)
    if got != chain["chain_id"]:
        raise ValueError(f"{name}: RPC chain id {got} != config {chain['chain_id']}")
    me = f.address()
    tx = f.send(rpc, chain["lreact_faucet"], "request(address)", [me], to_wei(amount))
    return {"chain": name, "faucet": chain["lreact_faucet"], "eth": amount, "tx": tx,
            "explorer": chain["explorer_tx"] + tx, "deployer_left": eth(f.balance(rpc, me))}


def print_status(rep):
    print(f"deployer {rep['deployer']}")
    for name, row in rep["chains"].items():
        sym = row["symbol"]
        print(f"{name}: deployer {row['deployer']} {sym}")
        if "keeper" in row:
            k = row["keeper"]
            print(f"  keeper {k['address']} balance {k['balance']} reserves {k['reserves']} owed {k['owed']} {sym}")
        if "tank" in row:
            print(f"  tank   {row['tank']['address']} balance {row['tank']['balance']} {sym}")
        for w in row.get("wards", []):
            print(f"  ward   {w['address']} {w['role']:<7} {w.get('name', '')} debt {w['debt']} reserves {w['reserves']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Pelita balances and faucet swap.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("status")
    st.add_argument("--json", action="store_true")
    st.add_argument("--out", default=str(pelitarpc.ROOT / "deployments"))
    tk = sub.add_parser("tukar")
    tk.add_argument("eth", help="ETH to swap on Base Sepolia (first try 0.01)")
    a = ap.parse_args(argv)
    chains = pelitarpc.load_config("chains.json")
    cfg = pelitarpc.load_config("pelita.json")
    rpcs = {n: rpc_for(n, c) for n, c in chains["chains"].items()}
    f = Foundry(auth_from_env(), cwd=pelitarpc.ROOT)
    try:
        if a.cmd == "status":
            rep = status(f, chains, a.out, rpcs)
            print(json.dumps(rep, indent=2)) if a.json else print_status(rep)
        else:
            print(json.dumps(tukar(f, chains, cfg, rpcs, a.eth), indent=2))
    except ValueError as e:
        print(f"funds: refused: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"funds: FAILED: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
