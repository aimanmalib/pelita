"""Spike evidence (PRD §4.4, ADR 0002): reads the spike loop back from the chains and writes docs/evidence/E-002-spike.json.

Nothing is typed by hand. The loop is followed from the Beacon beat on Base Sepolia:
  beat tx (Base Sepolia) -> the Flicker reaction on Lasna whose receipt `refTx` is the beat -> the Keeper reaction
  whose `refTx` is the Flicker reaction.
S1 holds when the Flicker reaction carries BlacklistContract(flicker) and the Keeper reacted to it.
S2 holds when the Keeper reaction carries both Refueled(target = flicker) and WhitelistContract(flicker) (one
transaction) and debt(flicker) reads 0 afterwards.

Usage: python3 scripts/spike/spike_evidence.py --beat <base sepolia tx> [--out docs/evidence/E-002-spike.json]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import pelitarpc  # noqa: E402

# topic0 = keccak256 of each signature (tests/test_spike_evidence.py recomputes them with `cast keccak` when Foundry
# is present). Standard library only, so there is no keccak here.
EVENTS = {
    "0x930136576d6bd679046e0c2e6212ce4cacec0401db71e9a27f906d2bab5e08f3": "BlacklistContract",
    "0xc91181be4112cf78026ec1c30b4f5ecac00faa44c8d5e9523e08325cf186d8a7": "WhitelistContract",
    "0x6aa407b0d47ebfb6ee8253c926e3693a433c59e15311b55919f645a932295268": "WentDark",
    "0x6222049514ff18fc44cce15aa27021d5c62df3b0f552942d1a13ede3c7344692": "Refueled",
    "0xc432b3e687365454eae929648bf87c45d0744ff46afb550613b4c18ecbdc60f8": "GaveUp",
    "0x24e16f88eda8ab342f0b5dd43bfbd9fa325d3518961b553e904bce379b8b8c49": "LowTank",
    "0x509da02d76b66d8370a76a9ed0b42a3de167a8a53d97b435f51441a53d557a4d": "Forwarded",
    "0xc419c96c78a72385d2431b7135a30707de0715c30e32ef75e7eb9d802137253d": "Beat",
}
SIGS = {
    "BlacklistContract": "BlacklistContract(address)",
    "WhitelistContract": "WhitelistContract(address)",
    "WentDark": "WentDark(uint256,address,uint256)",
    "Refueled": "Refueled(uint256,address,uint256,uint256,uint256)",
    "GaveUp": "GaveUp(uint256,address,uint8)",
    "LowTank": "LowTank(uint256)",
    "Forwarded": "Forwarded(uint256,uint256)",
    "Beat": "Beat(uint256,uint256)",
}
DEBT_SELECTOR = "0x9b6c56ec"  # debt(address)


def addr(topic):
    return "0x" + topic[-40:].lower()


def words(data):
    data = data[2:]
    return [int(data[i:i + 64], 16) for i in range(0, len(data), 64)]


def summarise(receipt, ts, names=EVENTS):
    logs = []
    for lg in receipt["logs"]:
        t = lg["topics"]
        row = {"address": lg["address"].lower(), "event": names.get(t[0].lower(), t[0]),
               "log_index": int(lg["logIndex"], 16)}
        if row["event"] in ("BlacklistContract", "WhitelistContract"):
            row["contract"] = addr(t[1])
        elif row["event"] in ("WentDark", "Refueled", "GaveUp"):
            row["chain_id"], row["target"] = int(t[1], 16), addr(t[2])
            w = words(lg["data"])
            if row["event"] == "Refueled":
                row["amount_wei"], row["owed_wei"], row["origin_block"] = w
            elif row["event"] == "GaveUp":
                row["reason"] = w[0]
        elif row["event"] == "LowTank":
            row["balance_wei"] = words(lg["data"])[0]
        logs.append(row)
    out = {"tx": receipt["transactionHash"], "block": int(receipt["blockNumber"], 16), "block_time": ts,
           "status": int(receipt["status"], 16), "from": receipt["from"].lower(), "to": (receipt["to"] or "").lower(),
           "gas_used": int(receipt["gasUsed"], 16), "logs": logs}
    if receipt.get("effectiveGasPrice"):
        out["fee_wei"] = out["gas_used"] * int(receipt["effectiveGasPrice"], 16)
    for k in ("refChainId", "refTx", "rnkTxType"):
        if receipt.get(k) is not None:
            out[k] = int(receipt[k], 16) if k == "refChainId" else receipt[k]
    return out


def find_reaction(rpc_logs, ref_tx):
    """First receipt among `rpc_logs` (receipts in block order) whose refTx is `ref_tx`."""
    for r in rpc_logs:
        if (r.get("refTx") or "").lower() == ref_tx.lower():
            return r
    return None


def verdict(flicker, keeper_rx, flicker_rx, debt_after):
    s1 = bool(flicker_rx and keeper_rx) and any(
        lg["event"] == "BlacklistContract" and lg.get("contract") == flicker for lg in flicker_rx["logs"])
    s2 = bool(keeper_rx) and any(
        lg["event"] == "Refueled" and lg.get("target") == flicker for lg in keeper_rx["logs"]) and any(
        lg["event"] == "WhitelistContract" and lg.get("contract") == flicker for lg in keeper_rx["logs"]) \
        and debt_after == 0
    return {"S1": s1, "S2": s2}


class Chain:
    def __init__(self, client, url):
        self.c, self.url = client, url

    def receipt(self, tx):
        return self.c.call(self.url, "eth_getTransactionReceipt", [tx])

    def block_time(self, number_hex):
        return int(self.c.call(self.url, "eth_getBlockByNumber", [number_hex, False])["timestamp"], 16)

    def reactions(self, start, end, step=50):
        """Receipts of reactive transactions (rnkTxType "r") in blocks start..end, batched `step` blocks a request."""
        out = []
        for lo in range(start, end + 1, step):
            blocks = self.c.batch(self.url, [("eth_getBlockByNumber", [hex(n), False])
                                             for n in range(lo, min(end, lo + step - 1) + 1)])
            hashes = [h for b in blocks for h in b["transactions"]]
            out += [r for r in self.c.batch(self.url, [("eth_getTransactionReceipt", [h]) for h in hashes])
                    if r.get("rnkTxType") == "r"]
        return out


def collect(lasna, base, deployments, biller, beat_tx, names=EVENTS, scan_blocks=200):
    keeper = deployments["lasna"]["keeper"].lower()
    flicker = deployments["lasna"]["contracts"]["flicker_guarded"]["address"].lower()
    beat = base.receipt(beat_tx)
    beat_s = summarise(beat, base.block_time(beat["blockNumber"]), names)
    first = deployments["lasna"]["contracts"]["flicker_guarded"]["block"]
    head = int(lasna.c.call(lasna.url, "eth_blockNumber"), 16)
    receipts = lasna.reactions(first, min(head, first + scan_blocks))
    fl = find_reaction(receipts, beat_tx)
    kp = find_reaction(receipts, fl["transactionHash"]) if fl else None
    fl_s = summarise(fl, lasna.block_time(fl["blockNumber"]), names) if fl else None
    kp_s = summarise(kp, lasna.block_time(kp["blockNumber"]), names) if kp else None
    debt = lasna.c.call(lasna.url, "eth_call", [{"to": biller, "data": DEBT_SELECTOR + flicker[2:].rjust(64, "0")},
                                                 "latest"])
    debt_after = int(debt, 16)
    return {"keeper": keeper, "flicker": flicker, "beat": beat_s, "flicker_reaction": fl_s, "keeper_reaction": kp_s,
            "flicker_debt_after_wei": debt_after, "verdict": verdict(flicker, kp_s, fl_s, debt_after)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--beat", required=True, help="Beacon pokeOwner() transaction on Base Sepolia")
    ap.add_argument("--scan-blocks", type=int, default=200, help="Lasna blocks after the Flicker deploy to search")
    ap.add_argument("--out", default=str(pelitarpc.ROOT / "docs" / "evidence" / "E-002-spike.json"))
    a = ap.parse_args(argv)
    chains = pelitarpc.load_config("chains.json")
    client = pelitarpc.Client(chains["user_agent"])
    lasna_cfg, base_cfg = chains["chains"]["lasna"], chains["chains"]["base-sepolia"]
    deps = {"lasna": json.loads((pelitarpc.ROOT / "deployments" / "lasna.json").read_text(encoding="utf-8"))}
    ev = collect(Chain(client, lasna_cfg["rpc"]), Chain(client, base_cfg["rpc"]), deps, lasna_cfg["biller"], a.beat,
                 scan_blocks=a.scan_blocks)
    ev = {"_about": "Spike S1/S2 (PRD 4.4, ADR 0002), read back from the chains by scripts/spike/spike_evidence.py.",
          "chains": {"lasna": lasna_cfg["chain_id"], "base-sepolia": base_cfg["chain_id"]}, **ev}
    Path(a.out).write_text(json.dumps(ev, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(ev["verdict"]))
    return 0 if all(ev["verdict"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
