"""Re-reads every value in config/chains.json from the chains themselves (read only, no key).

collect() talks to the network; judge() is pure and compares readings with config, so the
comparison is tested offline on a recorded fixture. Output: docs/evidence/E-001-chain-facts.json.
"""

import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import pelitarpc  # noqa: E402

FEE_GETTERS = {
    "gas_price_coeff_per_1000": "_gasPriceCoeffPer1000()",
    "extra_gas": "_extraGas()",
    "max_charge_gas": "_maxChargeGas()",
}
REF_FIELDS = ("refChainId", "refTx", "refEventIndex", "rnkTxType")


def cast(*args):
    exe = os.environ.get("CAST", str(Path.home() / ".foundry/bin/cast"))
    return subprocess.run([exe, *args], check=True, capture_output=True, text=True).stdout.strip()


def computed_constants(cfg):
    """Topic hashes and selectors recomputed with `cast` (no network)."""
    topics = {sig: cast("keccak", sig) for sig in cfg["topics"]}
    selectors = {sig: cast("sig", sig) for sig in cfg["selectors"] if "(" in sig}
    return {"topics": topics, "selectors": selectors}


def _try(fn):
    try:
        return {"ok": True, "value": fn()}
    except Exception as e:  # recorded, never raised: one bad reading must not hide the others
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}


def read_chain(client, chain, latest_logs_probe=True):
    url = chain["rpc"]
    r = {"rpc": url}
    r["chain_id"] = _try(lambda: int(client.call(url, "eth_chainId"), 16))
    r["block"] = _try(lambda: int(client.call(url, "eth_blockNumber"), 16))
    r["gas_price_wei"] = _try(lambda: int(client.call(url, "eth_gasPrice"), 16))
    r["biller_code_bytes"] = _try(lambda: (len(client.call(url, "eth_getCode", [chain["biller"], "latest"])) - 2) // 2)
    for key, sig in FEE_GETTERS.items():
        data = cast("calldata", sig)
        r["fee_" + key] = _try(
            lambda d=data: int(client.call(url, "eth_call", [{"to": chain["biller"], "data": d}, "latest"]), 16)
        )
    if "lreact_faucet" in chain:
        r["faucet_code_bytes"] = _try(
            lambda: (len(client.call(url, "eth_getCode", [chain["lreact_faucet"], "latest"])) - 2) // 2
        )
    cap = chain.get("get_logs_max_blocks")
    if cap and latest_logs_probe and r["block"]["ok"]:
        top = r["block"]["value"]
        for label, span in (("at_cap", cap), ("over_cap", cap + 1)):
            lo = top - span + 1
            r["logs_" + label] = _try(
                lambda lo=lo: len(
                    client.call(url, "eth_getLogs", [{"address": chain["biller"], "fromBlock": hex(lo), "toBlock": hex(top)}])
                )
            )
    return r


def read_lasna_extras(client, cfg, chain, s1_pairs):
    """Live trigger selector and topic order on the newest blacklisting, CORS, and the S1 receipts."""
    url = chain["rpc"]
    out = {}
    top = int(client.call(url, "eth_blockNumber"), 16)
    span = chain["get_logs_max_blocks"]
    black = cfg["topics"]["BlacklistContract(address)"]
    logs = []
    for i in range(4):  # newest windows first, stop at the first blacklisting found
        hi = top - i * span
        logs = client.call(url, "eth_getLogs", [{"address": chain["biller"], "topics": [black],
                                                 "fromBlock": hex(hi - span + 1), "toBlock": hex(hi)}])
        if logs:
            break
    if logs:
        tx_hash = logs[-1]["transactionHash"]
        tx = client.call(url, "eth_getTransactionByHash", [tx_hash])
        rc = client.call(url, "eth_getTransactionReceipt", [tx_hash])
        out["latest_blacklisting"] = {
            "tx": tx_hash,
            "block": int(rc["blockNumber"], 16),
            "selector": tx["input"][:10],
            "to": tx["to"],
            "topics_in_order": [l["topics"][0] for l in rc["logs"] if l["address"].lower() == chain["biller"].lower()],
        }
    status, head, _ = client.request(url, {"jsonrpc": "2.0", "id": 1, "method": "eth_chainId", "params": []},
                                     {"Origin": "https://pelita.sasateguh.com"})
    out["cors_allow_origin"] = head.get("access-control-allow-origin")
    out["s1_pairs"] = []
    for pair in s1_pairs:
        rc = client.call(url, "eth_getTransactionReceipt", [pair["reaction"]])
        out["s1_pairs"].append({
            "blacklisting": pair["blacklisting"],
            "reaction": pair["reaction"],
            "reaction_block": int(rc["blockNumber"], 16),
            "status": int(rc["status"], 16),
            **{k: rc.get(k) for k in REF_FIELDS},
        })
        out["s1_pairs"][-1]["blacklisting_block"] = int(
            client.call(url, "eth_getTransactionReceipt", [pair["blacklisting"]])["blockNumber"], 16
        )
    return out


def judge(cfg, readings, constants):
    """Pure: one check per config value. Returns a list of {check, expected, measured, ok}."""
    checks = []

    def add(name, expected, measured, ok=None):
        checks.append({"check": name, "expected": expected, "measured": measured,
                       "ok": (expected == measured) if ok is None else ok})

    for sig, value in cfg["topics"].items():
        add(f"topic {sig}", value, constants["topics"].get(sig))
    for sig, value in cfg["selectors"].items():
        if sig in constants["selectors"]:
            add(f"selector {sig}", value, constants["selectors"][sig])
    for name, chain in cfg["chains"].items():
        r = readings["chains"].get(name)
        if r is None:
            continue
        val = lambda k: r[k]["value"] if r.get(k, {}).get("ok") else None  # noqa: E731
        add(f"{name} chain_id", chain["chain_id"], val("chain_id"))
        code = val("biller_code_bytes")
        add(f"{name} biller has code", True, bool(code), code is not None and code > 0)
        for key in FEE_GETTERS:
            add(f"{name} fee {key}", chain["fees"][key], val("fee_" + key))
        if "gas_price_gwei" in chain["fees"]:
            gp = val("gas_price_wei")
            add(f"{name} gas price gwei", chain["fees"]["gas_price_gwei"], None if gp is None else gp / 1e9,
                gp is not None and abs(gp / 1e9 - chain["fees"]["gas_price_gwei"]) <= chain["fees"]["gas_price_gwei"] * 0.5)
        if "lreact_faucet" in chain:
            fc = val("faucet_code_bytes")
            add(f"{name} lREACT faucet has code", True, bool(fc), fc is not None and fc > 0)
        if "logs_at_cap" in r:
            add(f"{name} eth_getLogs {chain['get_logs_max_blocks']} blocks accepted", True, r["logs_at_cap"]["ok"])
            add(f"{name} eth_getLogs one block over the cap refused", False, r["logs_over_cap"]["ok"])
    extra = readings.get("lasna_extras") or {}
    latest = extra.get("latest_blacklisting")
    if latest:
        add("trigger selector on the newest blacklisting", cfg["selectors"]["trigger"], latest["selector"])
        add("blacklisting tx: PaymentFailure then BlacklistContract",
            [cfg["topics"]["PaymentFailure(address,uint256)"], cfg["topics"]["BlacklistContract(address)"]],
            latest["topics_in_order"][-2:])
    if "cors_allow_origin" in extra:
        add("Lasna RPC CORS reflects the page origin", "https://pelita.sasateguh.com", extra["cors_allow_origin"],
            extra["cors_allow_origin"] in ("https://pelita.sasateguh.com", "*"))
    for p in extra.get("s1_pairs", []):
        add(f"S1 reaction {p['reaction'][:10]} refTx = blacklisting", p["blacklisting"], p.get("refTx"),
            (p.get("refTx") or "").lower() == p["blacklisting"].lower() and p["status"] == 1)
    return checks


def main():
    cfg = pelitarpc.load_config("chains.json")
    client = pelitarpc.Client(cfg["user_agent"])
    started = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    readings = {"chains": {name: read_chain(client, ch) for name, ch in cfg["chains"].items()}}
    lasna = next(ch for ch in cfg["chains"].values() if ch["reactive"] and ch["aktif"])
    readings["lasna_extras"] = _try(lambda: read_lasna_extras(client, cfg, lasna, cfg["s1_observed_pairs"]))
    readings["lasna_extras"] = readings["lasna_extras"].get("value") or readings["lasna_extras"]
    constants = computed_constants(cfg)
    checks = judge(cfg, readings, constants)
    active = {n for n, ch in cfg["chains"].items() if ch["aktif"]}
    failed_active = [c for c in checks if not c["ok"] and not any(c["check"].startswith(n) for n in set(cfg["chains"]) - active)]
    doc = {
        "id": "E-001",
        "title": "Chain facts re-read from the chains",
        "measured_at_utc": started,
        "method": "scripts/spike/readonly.sh: JSON-RPC reads only (eth_chainId, eth_call, eth_getCode, eth_getLogs, "
                  "receipts); topics and selectors recomputed with cast keccak / cast sig.",
        "summary": {"checks": len(checks), "failed": sum(not c["ok"] for c in checks),
                    "failed_on_active_chains": len(failed_active)},
        "checks": checks,
        "readings": readings,
        "constants": constants,
    }
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else pelitarpc.ROOT / "docs/evidence/E-001-chain-facts.json"
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, out)
    for c in checks:
        print(("ok  " if c["ok"] else "BAD ") + c["check"] + ("" if c["ok"] else f"  expected={c['expected']} measured={c['measured']}"))
    print(f"E-001: {doc['summary']}")
    return 1 if failed_active else 0


if __name__ == "__main__":
    sys.exit(main())
