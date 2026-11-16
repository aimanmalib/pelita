"""Idempotent Pelita deployment (scripts/deploy.sh). Transactions go through `forge create` / `cast send` (foundry.py).

Order follows the organiser's documents: the reactive contract first, then the callback contract that needs its
address, then the wiring (chains, lantern, wards), then funding. Every step first reads the chain and does nothing
when the state is already there, so a second run sends no transaction. deployments/<chain>.json is rewritten
atomically after every step, so an interrupted run resumes where it stopped.

The file keeps the shape the indexer reads (ADR 0004): `keeper` or `tank`, `deploy_block`, `wards[]` with `role`.
"""

import json
import os
import tempfile
from pathlib import Path

from foundry import to_wei

SPECS = {
    "keeper": ("src/PelitaKeeper.sol:PelitaKeeper", "constructor(uint256,uint256)"),
    "tank": ("src/PelitaTank.sol:PelitaTank", "constructor(address,address,uint256,uint256)"),
    "beacon": ("src/demo/Beacon.sol:Beacon", "constructor(uint256,uint256,uint256)"),
    "flicker": ("src/demo/Flicker.sol:Flicker", "constructor(uint256,address,uint64)"),
    "lantern": ("src/demo/Lantern.sol:Lantern", "constructor(address,address)"),
}
ROLES = ("guarded", "control")
ZERO = "0x0000000000000000000000000000000000000000"
WARD_SIG = "ward(uint256,address)((uint256,address,uint256,uint256,uint32,uint32,uint64,uint64,bool,bool))"


class DeployError(Exception):
    pass


def last_bool(text):
    """`cast call` prints tuples and multi-value returns as text; the last true/false is the flag we want."""
    t, f = text.rfind("true"), text.rfind("false")
    if t < 0 and f < 0:
        raise DeployError(f"no boolean in: {text[-120:]}")
    return t > f


def _addresses(args):
    return [a.lower() for a in args if str(a).startswith("0x")]


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


class Side:
    """One chain: its RPC, config and deployments file."""

    def __init__(self, name, chain, rpc, out_dir, verifier):
        self.name, self.chain, self.rpc, self.verifier = name, chain, rpc, verifier
        self.path = Path(out_dir) / f"{name}.json"
        self.data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.data.setdefault("chain_id", chain["chain_id"])
        self.data.setdefault("contracts", {})

    @property
    def contracts(self):
        return self.data["contracts"]

    def save(self, own_role, demo_kind):
        c = self.contracts
        own = c.get(own_role)
        if own:
            self.data[own_role] = own["address"]
            self.data["deploy_block"] = own["block"]
        if "beacon" in c:
            self.data["beacon"] = c["beacon"]["address"]
        self.data["wards"] = [
            {"address": c[f"{demo_kind}_{r}"]["address"], "role": r, "name": demo_kind.capitalize()}
            for r in ROLES
            if f"{demo_kind}_{r}" in c
        ]
        write_json(self.path, self.data)


class Deployer:
    def __init__(self, foundry, chains_cfg, pelita_cfg, rpcs, out_dir, verify=True, demo=True, log=print):
        self.f, self.cfg, self.verify_on, self.demo, self.log = foundry, pelita_cfg, verify, demo, log
        chains = chains_cfg["chains"]
        active = [n for n, c in chains.items() if c.get("aktif")]
        react = [n for n in active if chains[n]["reactive"]]
        dest = [n for n in active if not chains[n]["reactive"]]
        if len(react) != 1 or len(dest) != 1:
            raise DeployError("config must have exactly one active reactive chain and one active destination")
        verifiers = pelita_cfg.get("deploy", {}).get("verifiers", {})
        self.r = Side(react[0], chains[react[0]], rpcs[react[0]], out_dir, verifiers.get(react[0]))
        self.d = Side(dest[0], chains[dest[0]], rpcs[dest[0]], out_dir, verifiers.get(dest[0]))
        self.sent = 0

    # --- steps -------------------------------------------------------------------------------------------------
    def check_chains(self):
        """Refuse to touch any chain whose id differs from config (no mainnet by accident)."""
        for side in (self.r, self.d):
            got = self.f.chain_id(side.rpc)
            if got != side.chain["chain_id"]:
                raise DeployError(f"{side.name}: RPC chain id {got} != config {side.chain['chain_id']}")

    def ensure_contract(self, side, key, kind, args, value_wei=0):
        rec = side.contracts.get(key)
        want = [str(a) for a in args]
        if rec and self.f.has_code(side.rpc, rec["address"]):
            if _addresses(rec["args"]) == _addresses(want):
                if rec["args"] != want:
                    self.log(f"! {side.name} {key}: config differs from constructor args {rec['args']}; use the setters")
                self.log(f"= {side.name} {key} {rec['address']}")
                return rec["address"]
            self.log(f"~ {side.name} {key}: a contract it points at was redeployed; deploying a new one")
        contract, _ = SPECS[kind]
        addr, tx = self.f.create(side.rpc, contract, [str(a) for a in args], value_wei)
        self.sent += 1
        side.contracts[key] = {
            "address": addr, "tx": tx, "block": self.f.receipt_block(side.rpc, tx),
            "kind": kind, "args": [str(a) for a in args], "verified": False,
        }
        self.log(f"+ {side.name} {key} {addr} tx {tx}")
        return addr

    def send_once(self, side, to, sig, args, label):
        tx = self.f.send(side.rpc, to, sig, [str(a) for a in args])
        self.sent += 1
        self.log(f"+ {side.name} {label} tx {tx}")
        return tx

    def ensure_chain(self, keeper, chain_id, biller, tank, gas):
        if last_bool(self.f.call(self.r.rpc, keeper, "chains(uint256)(address,address,uint64,bool)", chain_id)):
            self.log(f"= keeper chain {chain_id} set")
            return
        self.send_once(self.r, keeper, "setChain(uint256,address,address,uint64)", [chain_id, biller, tank, gas],
                       f"setChain {chain_id}")

    def ensure_lantern(self, flicker, lantern):
        cur = self.f.call(self.r.rpc, flicker, "lantern()(address)")
        if cur.lower() == lantern.lower():
            self.log(f"= flicker {flicker} lantern set")
            return
        if cur.lower() != ZERO:
            raise DeployError(f"flicker {flicker} already points at {cur}, not {lantern}")
        self.send_once(self.r, flicker, "setLantern(address)", [lantern], "setLantern")

    def ensure_ward(self, keeper, chain_id, target, ward_cfg, daily_cap):
        if last_bool(self.f.call(self.r.rpc, keeper, WARD_SIG, chain_id, target)):
            self.log(f"= ward {chain_id} {target} active")
            return
        args = [chain_id, target, to_wei(ward_cfg["refill"]), to_wei(ward_cfg["max_owed"]), daily_cap]
        self.send_once(self.r, keeper, "protect(uint256,address,uint256,uint256,uint32)", args, f"protect {target}")

    def ensure_balance(self, side, address, target_wei, label):
        have = self.f.balance(side.rpc, address)
        if have >= target_wei:
            self.log(f"= {label} balance {have} >= {target_wei}")
            return
        tx = self.f.send(side.rpc, address, None, (), target_wei - have)
        self.sent += 1
        self.log(f"+ {label} plain transfer {target_wei - have} wei tx {tx}")

    def verify_all(self):
        for side in (self.r, self.d):
            if not side.verifier:
                continue
            for key, rec in side.contracts.items():
                if rec.get("verified"):
                    continue
                contract, sig = SPECS[rec["kind"]]
                try:
                    self.f.verify(rec["address"], contract, side.chain["chain_id"], sig, rec["args"],
                                  side.verifier["verifier"], side.verifier.get("verifier_url"))
                    rec["verified"] = side.verifier["verifier"]
                    self.log(f"v {side.name} {key} verified ({rec['verified']})")
                except Exception as e:  # verification is retried on the next run; it never blocks a deploy
                    self.log(f"! {side.name} {key} not verified yet: {e}")
            self._save(side)

    def _save(self, side):
        side.save("keeper" if side is self.r else "tank", "flicker" if side is self.r else "lantern")

    # --- whole run ---------------------------------------------------------------------------------------------
    def run(self):
        self.check_chains()
        cfg, r, d = self.cfg, self.r, self.d
        rid, did = r.chain["chain_id"], d.chain["chain_id"]
        k, dest = cfg["keeper"], cfg["destinations"][d.name]

        keeper = self.ensure_contract(r, "keeper", "keeper", [to_wei(k["self_floor"]), to_wei(k["low_mark"])])
        self._save(r)
        tank = self.ensure_contract(d, "tank", "tank", [d.chain["biller"], keeper, to_wei(dest["tank_self_floor"]),
                                                         to_wei(dest["tank_max_per_refuel"])])
        self._save(d)
        self.ensure_chain(keeper, rid, r.chain["biller"], ZERO, 0)
        self.ensure_chain(keeper, did, d.chain["biller"], tank, dest["callback_gas"])

        if self.demo:
            self.deploy_demo(keeper, rid, did)

        funds = cfg["funds"]
        self.ensure_balance(r, keeper, to_wei(funds["keeper_fund"]), "keeper")
        self.ensure_balance(d, tank, to_wei(funds["tank_fund"]), "tank")
        if self.verify_on:
            self.verify_all()
        self._save(r)
        self._save(d)
        return self.sent

    def deploy_demo(self, keeper, rid, did):
        cfg, r, d = self.cfg, self.r, self.d
        demo = cfg["demo"]
        beacon = self.ensure_contract(d, "beacon", "beacon", [demo["beacon_cooldown_seconds"],
                                                              demo["beacon_max_beats_per_window"],
                                                              demo["beacon_window_seconds"]])
        self._save(d)
        pairs = {}
        for role in ROLES:
            flicker = self.ensure_contract(r, f"flicker_{role}", "flicker", [did, beacon, demo["flicker_callback_gas"]],
                                           to_wei(demo["flicker_fund"]))
            self._save(r)
            lantern = self.ensure_contract(d, f"lantern_{role}", "lantern", [d.chain["biller"], flicker],
                                           to_wei(demo["lantern_fund"]))
            self._save(d)
            self.ensure_lantern(flicker, lantern)
            pairs[role] = (flicker, lantern)
        cap = cfg["wards"]["demo"]["daily_cap"]
        flicker, lantern = pairs["guarded"]
        self.ensure_ward(keeper, rid, flicker, cfg["wards"][r.name], cap)
        self.ensure_ward(keeper, did, lantern, cfg["wards"][d.name], cap)


def main(argv=None):
    import argparse
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import pelitarpc
    from foundry import Foundry, auth_from_env

    ap = argparse.ArgumentParser(description="Deploy Pelita (idempotent). RPCs: PELITA_RPC_<CHAIN> overrides config.")
    ap.add_argument("--out", default=str(pelitarpc.ROOT / "deployments"), help="folder for <chain>.json")
    ap.add_argument("--no-verify", action="store_true", help="skip source verification (local anvil)")
    ap.add_argument("--no-demo", action="store_true", help="Keeper and Tank only, no Beacon/Flicker/Lantern")
    a = ap.parse_args(argv)
    chains = pelitarpc.load_config("chains.json")
    cfg = pelitarpc.load_config("pelita.json")
    rpcs = {n: rpc_for(n, c) for n, c in chains["chains"].items()}
    f = Foundry(auth_from_env(), cwd=pelitarpc.ROOT)
    d = Deployer(f, chains, cfg, rpcs, a.out, verify=not a.no_verify, demo=not a.no_demo)
    try:
        sent = d.run()
    except Exception as e:
        print(f"deploy: FAILED: {e}", file=sys.stderr)
        return 1
    print(f"deploy: OK ({sent} transactions sent; files in {a.out})")
    return 0


def rpc_for(name, chain, env=None):
    env = os.environ if env is None else env
    return env.get("PELITA_RPC_" + name.upper().replace("-", "_"), chain["rpc"])


if __name__ == "__main__":
    raise SystemExit(main())
