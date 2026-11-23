"""Spike S1/S2 on Lasna with the real contracts (PRD §4.4, ADR 0002).

Deploys only what the Lasna loop needs, through the same idempotent Deployer as scripts/deploy.sh and into the same
deployments/<chain>.json, so P2b later resumes from here instead of paying for the contracts twice:
  Lasna: PelitaKeeper (config args), setChain(Lasna), Flicker `guarded` (funded with --flicker-fund only, so it goes
         dark on its first reaction), protect(Lasna, Flicker), Keeper topped up to --keeper-fund.
  Base Sepolia: Beacon, Lantern `guarded`.
Then `--beat` sends one Beacon.pokeOwner() so the Flicker reacts, runs out of lREACT and is blacklisted; the Keeper
should hear BlacklistContract (S1) and pay the debt with depositTo inside react() (S2). The outcome is read from the
chain afterwards (scripts/spike/spike_evidence.py), never assumed here.

Usage: python3 scripts/spike/lasna_spike.py --keeper-fund 0.4 --flicker-fund 0.005 [--beat]
"""

import argparse
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import pelitarpc  # noqa: E402
from deployer import ZERO, Deployer, rpc_for  # noqa: E402
from foundry import Foundry, auth_from_env, to_wei  # noqa: E402


def run(d, keeper_fund, flicker_fund, beat):
    cfg, r, dst = d.cfg, d.r, d.d
    rid, did = r.chain["chain_id"], dst.chain["chain_id"]
    d.check_chains()
    k, demo = cfg["keeper"], cfg["demo"]
    d.check_callback_gas(demo["flicker_callback_gas"])
    keeper = d.ensure_contract(r, "keeper", "keeper", [to_wei(k["self_floor"]), to_wei(k["low_mark"])])
    d._save(r)
    d.ensure_chain(keeper, rid, r.chain["biller"], ZERO, 0)
    beacon = d.ensure_contract(dst, "beacon", "beacon", [demo["beacon_cooldown_seconds"],
                                                          demo["beacon_max_beats_per_window"],
                                                          demo["beacon_window_seconds"]])
    d._save(dst)
    flicker = d.ensure_contract(r, "flicker_guarded", "flicker", [did, beacon, demo["flicker_callback_gas"]],
                                to_wei(flicker_fund))
    d._save(r)
    lantern = d.ensure_contract(dst, "lantern_guarded", "lantern", [dst.chain["biller"], flicker],
                                to_wei(demo["lantern_fund"]))
    d._save(dst)
    d.ensure_lantern(flicker, lantern)
    d.ensure_ward(keeper, rid, flicker, cfg["wards"][r.name], cfg["wards"]["demo"]["daily_cap"])
    d.release_retired(keeper, r, rid)
    d.ensure_balance(r, keeper, to_wei(keeper_fund), "keeper")
    d._save(r)
    if beat:
        d.send_once(dst, beacon, "pokeOwner()", [], "beacon pokeOwner")
    return {"keeper": keeper, "beacon": beacon, "flicker": flicker, "lantern": lantern}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--keeper-fund", required=True, help="lREACT the Keeper is topped up to (plain transfer)")
    ap.add_argument("--flicker-fund", required=True, help="lREACT the guarded Flicker is created with")
    ap.add_argument("--beat", action="store_true", help="send one Beacon.pokeOwner() at the end")
    ap.add_argument("--out", default=str(pelitarpc.ROOT / "deployments"))
    a = ap.parse_args(argv)
    chains = pelitarpc.load_config("chains.json")
    cfg = copy.deepcopy(pelitarpc.load_config("pelita.json"))
    rpcs = {n: rpc_for(n, c) for n, c in chains["chains"].items()}
    f = Foundry(auth_from_env(), cwd=pelitarpc.ROOT)
    d = Deployer(f, chains, cfg, rpcs, a.out, verify=False)
    try:
        out = run(d, a.keeper_fund, a.flicker_fund, a.beat)
    except Exception as e:
        print(f"spike: FAILED: {e}", file=sys.stderr)
        return 1
    print(f"spike: OK ({d.sent} transactions sent) {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
