"""Measurement series for H1-H5 (PRD 2.1, 4.5). Two commands:

record  Read-only, no key. Reads, from each chain's deploy block to its tip: every dark/lit event of the demo wards
        (guarded and control), every Keeper reaction on Lasna with its receipt (`refTx`, fee), every Tank callback on
        the destination, and the Beacon beats and Lantern lights for H4. Writes docs/evidence/E-005-series-<side>.json.
        A reaction is paired with its outage EXACTLY: the reactive transaction's `refTx` is the outage transaction.
        Times are block timestamps, never this script's clock.
poke    Sends `pokeOwner()` to the Beacon N times, `--interval` seconds apart (Foundry keystore; drives the demo).
"""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
for p in (HERE.parent / "lib", HERE.parent, HERE.parent.parent / "ops"):
    sys.path.insert(0, str(p))
import census  # noqa: E402
import fleet  # noqa: E402
import pelitarpc  # noqa: E402

BEAT = "Beat(uint256,uint256)"
LIT_DEMO = "Lit(uint256,uint256,uint256)"
REACTIONS = ("Refueled", "RefuelRequested", "GaveUp")


def _int(v):
    return census._int(v) if v not in (None, "", "0x") else 0


# --- pure pairing (tested on fixtures) ----------------------------------------------------------------------------
def build_rows(side, wards, darks, lits, reactions, callbacks):
    """One row per outage of a demo ward.

    wards     {address: role}
    darks     [{address, block, log_index, tx, ts}] on the side's chain (BlacklistContract)
    lits      [{address, block, tx, ts}] on the side's chain (WhitelistContract)
    reactions [{event, target, tx, block, ts, ref_tx, fee_wei, seq?, reason?}] Keeper events on Lasna, with receipts
    callbacks [{seq, target, tx, block, ts, fee_wei, event, reason?}] Tank events on the destination (empty on Lasna)
    """
    rows = []
    darks = sorted((d for d in darks if d["address"].lower() in wards), key=lambda d: (d["block"], d["log_index"]))
    by_ref = {}
    for r in reactions:
        if r["event"] in REACTIONS and r.get("ref_tx"):
            by_ref.setdefault(r["ref_tx"].lower(), []).append(r)
    by_seq = {c["seq"]: c for c in callbacks if c.get("seq") is not None}
    for i, d in enumerate(darks):
        addr = d["address"].lower()
        nxt = next((x["ts"] for x in darks[i + 1 :] if x["address"].lower() == addr), None)
        row = {"side": side, "role": wards[addr], "target": addr,
               "dark_tx": d["tx"], "dark_block": d["block"], "dark_ts": d["ts"]}
        mine = [r for r in by_ref.get(d["tx"].lower(), []) if r.get("target", "").lower() == addr]
        if mine:
            r = mine[0]
            row.update(reaction_tx=r["tx"], reaction_block=r["block"], reaction_ts=r["ts"],
                       reaction_fee_wei=r.get("fee_wei", 0), outcome=r["event"])
            if r.get("reason"):
                row["reason"] = r["reason"]
            cb = by_seq.get(r.get("seq")) if r["event"] == "RefuelRequested" else None
            if cb:
                row.update(callback_tx=cb["tx"], callback_ts=cb["ts"], callback_fee_wei=cb.get("fee_wei", 0),
                           callback_event=cb["event"])
                if cb.get("reason"):
                    row["callback_reason"] = cb["reason"]
        lit = next((x for x in sorted(lits, key=lambda x: x["block"]) if x["address"].lower() == addr
                    and x["ts"] >= d["ts"] and (nxt is None or x["ts"] <= nxt)), None)
        if lit:
            row.update(lit_tx=lit["tx"], lit_ts=lit["ts"], latency_s=lit["ts"] - d["ts"])
        rows.append(row)
    return rows


def control_status(rows, debts, as_of_ts):
    """H3: each control ward, whether it is still dark at the last block read, for how long, and its debt there."""
    out = []
    for addr, debt in debts.items():
        mine = [r for r in rows if r["target"] == addr]
        last = mine[-1] if mine else None
        dark = bool(last) and "lit_tx" not in last
        out.append({"address": addr, "dark": dark, "debt_wei": debt,
                    "dark_since_ts": last["dark_ts"] if dark else None,
                    "hours_dark": round((as_of_ts - last["dark_ts"]) / 3600, 1) if dark else 0})
    return out


def read_debt(client, chain, selector, address, block):
    data = selector + address.lower()[2:].rjust(64, "0")
    return _int(client.call(chain["rpc"], "eth_call", [{"to": chain["biller"], "data": data}, hex(block)]))


def summarize(rows, role="guarded"):
    mine = [r for r in rows if r["role"] == role]
    lat = sorted(r["latency_s"] for r in mine if "latency_s" in r)
    return {
        "outages": len(mine),
        "relit": len(lat),
        "relit_pct": round(100 * len(lat) / len(mine), 1) if mine else None,
        "median_s": statistics.median(lat) if lat else None,
        "max_s": lat[-1] if lat else None,
        "reaction_fee_wei": [r["reaction_fee_wei"] for r in mine if "reaction_fee_wei" in r],
        "callback_fee_wei": [r["callback_fee_wei"] for r in mine if "callback_fee_wei" in r],
    }


# --- chain reads --------------------------------------------------------------------------------------------------
def blockscout_logs(client, chain, address, topic0, first, last, page_size=census.BLOCKSCOUT_PAGE):
    out, page = [], 1
    while True:
        url = (f"{chain['blockscout_api']}?module=logs&action=getLogs&address={address}&topic0={topic0}"
               f"&fromBlock={first}&toBlock={last}&page={page}&offset={page_size}")
        _, _, text = client.request(url)
        reply = json.loads(text)
        rows = reply.get("result") or []
        if not isinstance(rows, list) or (reply.get("status") != "1" and rows):
            raise pelitarpc.RpcError(f"blockscout: {reply.get('message')} {rows if not isinstance(rows, list) else ''}")
        out += rows
        if len(rows) < page_size:
            return out
        page += 1


def keeper_reactions(client, reader, dep, events_cfg, first, last):
    lasna = reader.chain
    topics = {t: sig for sig, t in events_cfg["keeper"].items()}
    logs = []
    for lo, hi in census.windows(first, last, lasna["get_logs_max_blocks"]):
        logs += client.call(lasna["rpc"], "eth_getLogs", [{"address": dep["keeper"], "topics": [list(topics)],
                                                           "fromBlock": hex(lo), "toBlock": hex(hi)}])
    logs = [lg for lg in logs if not lg.get("removed") and lg["topics"][0] in topics]
    events = fleet.decode_events(logs, topics, events_cfg["reasons"], "")
    for e, lg in zip(events, logs):
        if e["event"] == "RefuelRequested":
            e["seq"] = _int(lg["topics"][3])
    txs = sorted({e["tx"] for e in events})
    receipts = dict(zip(txs, client.batch(lasna["rpc"], [("eth_getTransactionReceipt", [t]) for t in txs])))
    reader.prefetch_times(e["block"] for e in events)
    for e in events:
        rc = receipts[e["tx"]] or {}
        e["ref_tx"] = rc.get("refTx")
        e["fee_wei"] = _int(rc.get("gasUsed")) * _int(rc.get("effectiveGasPrice"))
        e["ts"] = reader.block_time(e["block"])
    return events


def tank_callbacks(client, dest, dep, events_cfg, first, last):
    topics = {t: sig for sig, t in events_cfg["tank"].items()}
    logs = []
    for t in topics:
        logs += blockscout_logs(client, dest, dep["tank"], t, first, last)
    out = []
    for lg in logs:
        name = topics[lg["topics"][0]].split("(")[0]
        item = {"event": name, "seq": _int(lg["topics"][1]), "target": "0x" + lg["topics"][2][-40:].lower(),
                "tx": lg["transactionHash"], "block": _int(lg["blockNumber"]), "ts": _int(lg["timeStamp"]),
                "fee_wei": _int(lg.get("gasUsed")) * _int(lg.get("gasPrice"))}
        if name == "Skipped":
            item["reason"] = events_cfg["reasons"]["Skipped"].get(str(_int(lg["data"][-64:])), "?")
        out.append(item)
    return out


def demo_counts(client, dest, dep, first, last):
    """H4: beats sent by the Beacon and lights seen by each Lantern over the same block range."""
    beat, lit = census_topic(BEAT), census_topic(LIT_DEMO)
    counts = {"beats": len(blockscout_logs(client, dest, dep["beacon"], beat, first, last))}
    for w in dep.get("wards", []):
        counts[f"lit_{w['role']}"] = len(blockscout_logs(client, dest, w["address"], lit, first, last))
    return counts


def census_topic(signature):
    return pelitarpc.load_config("events.json")["demo"][signature]


def record(client, chains, events_cfg, root, side):
    names = [n for n, c in chains["chains"].items() if c.get("aktif")]
    lasna_name = next(n for n in names if chains["chains"][n]["reactive"])
    dest_name = next(n for n in names if not chains["chains"][n]["reactive"])
    deps = fleet.load_deployments(root, [lasna_name, dest_name])
    if lasna_name not in deps or (side != lasna_name and dest_name not in deps):
        raise SystemExit("series: deployments/<chain>.json missing; run scripts/deploy.sh first")
    lasna, ldep = chains["chains"][lasna_name], deps[lasna_name]
    lreader = census.ChainReader(client, lasna, chains["topics"])
    lfirst, llast = ldep["deploy_block"], lreader.latest_block()
    reactions = keeper_reactions(client, lreader, ldep, events_cfg, lfirst, llast)
    ranges = {lasna_name: [lfirst, llast]}
    if side == lasna_name:
        dep, reader, first, last, callbacks = ldep, lreader, lfirst, llast, []
    else:
        chain, dep = chains["chains"][dest_name], deps[dest_name]
        reader = census.ChainReader(client, chain, chains["topics"])
        first, last = dep["deploy_block"], reader.latest_block()
        callbacks = tank_callbacks(client, chain, dep, events_cfg, first, last)
        ranges[dest_name] = [first, last]
    events = reader.fetch(first, last)
    wards = {w["address"].lower(): w["role"] for w in dep.get("wards", [])}
    darks = [e for e in events if e["kind"] == "dark"]
    lits = [e for e in events if e["kind"] == "lit"]
    rows = build_rows(side, wards, darks, lits, reactions, callbacks)
    as_of = reader.block_time(last)
    debts = {a: read_debt(client, reader.chain, chains["selectors"]["debt(address)"], a, last) for a, role in wards.items() if role == "control"}
    out = {"side": side, "block_ranges": ranges, "as_of_ts": as_of, "rows": rows,
           "summary": {"guarded": summarize(rows, "guarded"), "control": summarize(rows, "control")},
           "controls": control_status(rows, debts, as_of)}
    if side != lasna_name:
        out["demo"] = demo_counts(client, chains["chains"][dest_name], dep, first, last)
    return out


def poke(count, interval, rpc=None):
    from deployer import rpc_for
    from foundry import Foundry, auth_from_env

    chains = pelitarpc.load_config("chains.json")
    name, chain = next((n, c) for n, c in chains["chains"].items() if c.get("aktif") and not c["reactive"])
    dep = fleet.load_deployments(pelitarpc.ROOT, [name])[name]
    f = Foundry(auth_from_env(), cwd=pelitarpc.ROOT)
    url = rpc or rpc_for(name, chain)
    if f.chain_id(url) != chain["chain_id"]:
        raise SystemExit("series: RPC chain id does not match config")
    for i in range(count):
        print(f"poke {i + 1}/{count} tx {f.send(url, dep['beacon'], 'pokeOwner()')}", flush=True)
        if i + 1 < count:
            time.sleep(interval)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record")
    rec.add_argument("--side", required=True, help="lasna or base-sepolia")
    rec.add_argument("--out", help="default docs/evidence/E-005-series-<side>.json")
    pk = sub.add_parser("poke")
    pk.add_argument("--count", type=int, default=1)
    pk.add_argument("--interval", type=int, default=60)
    a = ap.parse_args(argv)
    if a.cmd == "poke":
        poke(a.count, a.interval)
        return 0
    chains = pelitarpc.load_config("chains.json")
    client = pelitarpc.Client(chains["user_agent"])
    data = record(client, chains, pelitarpc.load_config("events.json"), pelitarpc.ROOT, a.side)
    out = Path(a.out or pelitarpc.ROOT / "docs" / "evidence" / f"E-005-series-{a.side}.json")
    out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    s = data["summary"]["guarded"]
    print(f"series {a.side}: {s['outages']} guarded outages, {s['relit']} relit, median {s['median_s']} s -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
