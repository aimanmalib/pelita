"""Demo loop evidence (PRD §0.3, P2c): follows one Beacon beat to the Lantern and writes docs/evidence/E-004-demo-loop.json.

Nothing is typed by hand. The loop is followed from the beat on Base Sepolia:
  beat tx (Base Sepolia) -> the Flicker reaction on Lasna whose receipt `refTx` is the beat (Forwarded + the system
  contract's callback request) -> callback proxy transactions on Base Sepolia in the blocks after the beat: the
  delivery whose calldata carries this Lantern, this beat's number and its origin block -> Lit on the Lantern.
A delivery that reverted is kept with its revert data (the same call re-run with eth_call from the same sender on the
parent block), and every other proxy transaction in the window (opening `context_blocks` before the beat) is listed by
selector, so a change on the operator side shows up next to the miss instead of being guessed at.

Usage: python3 scripts/spike/demo_loop_evidence.py --beat <base sepolia tx> [--out docs/evidence/E-004-demo-loop.json]
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import pelitarpc  # noqa: E402
import spike_evidence as se  # noqa: E402

# Topic of the system contract log that a reactive contract's callback request leaves on Lasna (topics: destination
# chain, requesting contract, recipient). Observed on the spike reaction (E-002); the signature is not published.
CALLBACK_REQUEST = "0xef94dbc611c4b95bf4b8ba34b413972180c2faf26fbb480befacedd83e07b133"
LIT = "Lit(uint256,uint256,uint256)"
# Proxy selectors named in the output; any other selector is kept as hex.
SELECTORS = {"0x8d1f0fa1": "deliverCallback", "0xe69cc4f0": "removeCallbackSenders",
             "0x3a93135f": "addCallbackSenders", "0xb760faf9": "depositTo"}


def word(n):
    return format(n, "x").rjust(64, "0")


def names(events_cfg):
    out = dict(se.EVENTS)
    out[CALLBACK_REQUEST] = "CallbackRequest"
    out[events_cfg["demo"][LIT].lower()] = "Lit"
    return out


def carries(tx_input, lantern, flicker, n, origin_block):
    """True when proxy calldata is addressed to this Lantern and holds lit(flicker, n, origin_block)."""
    body = (tx_input or "").lower()
    return word(int(lantern, 16)) in body and (word(int(flicker, 16)) + word(n) + word(origin_block)) in body


def block_at(chain, ts, lo, hi):
    """Highest block in lo..hi whose timestamp is <= ts (binary search, one request a step)."""
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if chain.block_time(hex(mid)) <= ts:
            lo = mid
        else:
            hi = mid - 1
    return lo


def proxy_txs(chain, proxy, first, last, step=50, pause=0.0, sleep=time.sleep):
    """Transactions sent to `proxy` in blocks first..last, in block order. The public Base Sepolia RPC counts each
    batch item against 25 requests a second (measured 23 Nov: -32007), so batches are `step` blocks `pause` s apart."""
    out = []
    for lo in range(first, last + 1, step):
        if lo > first:
            sleep(pause)
        blocks = chain.c.batch(chain.url, [("eth_getBlockByNumber", [hex(n), True])
                                           for n in range(lo, min(last, lo + step - 1) + 1)])
        out += [t for b in blocks for t in b["transactions"] if (t.get("to") or "").lower() == proxy]
    return out


def revert_data(chain, tx):
    """Revert data of `tx` re-run as eth_call from the same sender on the parent block ('' when it does not revert)."""
    call = {"from": tx["from"], "to": tx["to"], "data": tx["input"]}
    _, _, text = chain.c.request(chain.url, {"jsonrpc": "2.0", "id": 1, "method": "eth_call",
                                             "params": [call, hex(int(tx["blockNumber"], 16) - 1)]})
    err = json.loads(text).get("error")
    return (err.get("data") or err.get("message") or "") if err else ""


def collect(lasna, base, deployments, proxy, events_cfg, beat_tx, base_blocks=150, lasna_blocks=60, rate=(50, 0.0),
            context_blocks=30):
    nm = names(events_cfg)
    beat_topic = events_cfg["demo"]["Beat(uint256,uint256)"].lower()
    flicker = deployments["lasna"]["contracts"]["flicker_guarded"]["address"].lower()
    lantern = deployments["base-sepolia"]["contracts"]["lantern_guarded"]["address"].lower()
    beat = base.receipt(beat_tx)
    beat_s = se.summarise(beat, base.block_time(beat["blockNumber"]), nm)
    beat_block = beat_s["block"]
    n = next(int(lg["topics"][1], 16) for lg in beat["logs"] if lg["topics"][0].lower() == beat_topic)

    first = deployments["lasna"]["contracts"]["flicker_guarded"]["block"]
    head = int(lasna.c.call(lasna.url, "eth_blockNumber"), 16)
    start = block_at(lasna, beat_s["block_time"], first, head)
    fl = se.find_reaction(lasna.reactions(start, min(head, start + lasna_blocks)), beat_tx)
    fl_s = se.summarise(fl, lasna.block_time(fl["blockNumber"]), nm) if fl else None
    requested = bool(fl) and any(lg["topics"][0].lower() == CALLBACK_REQUEST and se.addr(lg["topics"][3]) == lantern
                                 for lg in fl["logs"])

    base_head = int(base.c.call(base.url, "eth_blockNumber"), 16)
    deliveries, others = [], []
    window = [max(0, beat_block - context_blocks), min(base_head, beat_block + base_blocks)]
    for tx in proxy_txs(base, proxy.lower(), *window, *rate):
        row = {"tx": tx["hash"], "block": int(tx["blockNumber"], 16), "from": tx["from"].lower(),
               "call": SELECTORS.get(tx["input"][:10].lower(), tx["input"][:10].lower())}
        if not carries(tx["input"], lantern, flicker, n, beat_block):
            others.append(row)
            continue
        rc = base.receipt(tx["hash"])
        row.update(se.summarise(rc, base.block_time(rc["blockNumber"]), nm))
        if row["status"] == 0:
            row["revert_data"] = revert_data(base, tx)
        deliveries.append(row)
    lit = any(lg["event"] == "Lit" and lg["address"] == lantern for d in deliveries for lg in d["logs"])
    return {"flicker": flicker, "lantern": lantern, "beat_number": n, "beat": beat_s, "flicker_reaction": fl_s,
            "deliveries": deliveries, "other_proxy_txs": others,
            "window": {"base_blocks": window},
            "verdict": {"forwarded": requested, "delivered": any(d["status"] == 1 for d in deliveries), "lit": lit}}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--beat", required=True, help="Beacon poke() or pokeOwner() transaction on Base Sepolia")
    ap.add_argument("--base-blocks", type=int, default=150, help="Base Sepolia blocks after the beat to search")
    ap.add_argument("--out", default=str(pelitarpc.ROOT / "docs" / "evidence" / "E-004-demo-loop.json"))
    a = ap.parse_args(argv)
    chains = pelitarpc.load_config("chains.json")
    client = pelitarpc.Client(chains["user_agent"])
    lasna_cfg, base_cfg = chains["chains"]["lasna"], chains["chains"]["base-sepolia"]
    deps = {k: json.loads((pelitarpc.ROOT / "deployments" / f"{k}.json").read_text(encoding="utf-8"))
            for k in ("lasna", "base-sepolia")}
    ev = collect(se.Chain(client, lasna_cfg["rpc"]), se.Chain(client, base_cfg["rpc"]), deps, base_cfg["biller"],
                 pelitarpc.load_config("events.json"), a.beat, base_blocks=a.base_blocks,
                 rate=(base_cfg["rpc_batch_max"], base_cfg["rpc_batch_pause_s"]))
    ev = {"_about": "Demo loop Beat -> Flicker -> Lit (PRD 0.3, P2c), read back from the chains by "
                    "scripts/spike/demo_loop_evidence.py.",
          "chains": {"lasna": lasna_cfg["chain_id"], "base-sepolia": base_cfg["chain_id"]}, "proxy": base_cfg["biller"],
          **ev}
    Path(a.out).write_text(json.dumps(ev, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(ev["verdict"]))
    return 0 if ev["verdict"]["lit"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
