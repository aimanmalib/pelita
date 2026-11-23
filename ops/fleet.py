"""Reads Pelita's own fleet (Keeper, Tank, wards) for the indexer. Read-only, no key.

The fleet comes from deployments/<chain>.json, written by scripts/deploy.sh:
  {"chain_id": 5318007, "keeper": "0x..", "deploy_block": 123,
   "wards": [{"address": "0x..", "role": "guarded" | "control", "name": "Lantern"}]}
  (the Base Sepolia file has "tank" instead of "keeper"). A missing file = that chain is not deployed yet.
"""

import json
from decimal import Decimal

import census

WEI = Decimal(10) ** 18


def ether(wei):
    return str((Decimal(wei) / WEI).normalize())


def load_deployments(root, names):
    out = {}
    for name in names:
        path = root / "deployments" / f"{name}.json"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                out[name] = json.load(f)
    return out


def _word(address):
    return address.lower().replace("0x", "").rjust(64, "0")


def read_status(client, chain, selectors, dep):
    """Balances and Omni debt/reserves for the Keeper or Tank and every ward, in one batch.

    A chain deployed only in part (wards before its Keeper or Tank, ADR 0002) gives `None` for the first value.
    """
    biller = chain["biller"]
    own = dep.get("keeper") or dep.get("tank")
    targets = ([own] if own else []) + [w["address"] for w in dep.get("wards", [])]
    calls = []
    for addr in targets:
        calls.append(("eth_getBalance", [addr, "latest"]))
        calls.append(("eth_call", [{"to": biller, "data": selectors["debt(address)"] + _word(addr)}, "latest"]))
        calls.append(("eth_call", [{"to": biller, "data": selectors["reserves(address)"] + _word(addr)}, "latest"]))
    results = client.batch(chain["rpc"], calls)
    rows = []
    for i, addr in enumerate(targets):
        bal, debt, res = (int(results[3 * i + k], 16) for k in range(3))
        rows.append({"address": addr.lower(), "balance_wei": bal, "debt_wei": debt, "reserves_wei": res})
    own_row, ward_rows = (rows[0], rows[1:]) if own else (None, rows)
    for row, ward in zip(ward_rows, dep.get("wards", [])):
        row["role"] = ward.get("role", "guarded")
        row["name"] = ward.get("name", "")
    if own_row is None:
        return None, ward_rows
    return {"role": "keeper" if dep.get("keeper") else "tank", **own_row}, ward_rows


def decode_events(logs, topic_names, reasons, chain_name):
    out = []
    for log in logs:
        name = topic_names.get(log["topics"][0])
        if not name:
            continue
        short = name.split("(")[0]
        item = {
            "chain": chain_name,
            "event": short,
            "block": int(log["blockNumber"], 16),
            "tx": log["transactionHash"],
        }
        if len(log["topics"]) > 2:
            item["target"] = "0x" + log["topics"][2][-40:].lower()
        if short in reasons:
            code = str(int(log["data"][-64:], 16))
            item["reason"] = reasons[short].get(code, code)
        out.append(item)
    return out


def read_events(client, chain, dep, events_cfg, first, last):
    """Pelita's own events (Keeper on Lasna, Tank on destinations) from `first` to `last`."""
    role = "keeper" if dep.get("keeper") else "tank"
    topic_names = {t: sig for sig, t in events_cfg[role].items()}
    logs = []
    for lo, hi in census.windows(first, last, chain["get_logs_max_blocks"]):
        logs += client.call(
            chain["rpc"],
            "eth_getLogs",
            [{"address": dep[role], "topics": [list(topic_names)], "fromBlock": hex(lo), "toBlock": hex(hi)}],
        )
    logs = [lg for lg in logs if not lg.get("removed")]
    logs.sort(key=lambda lg: (int(lg["blockNumber"], 16), int(lg["logIndex"], 16)))
    return decode_events(logs, topic_names, events_cfg["reasons"], chain.get("name", ""))


def read_demo(client, chain_name, chain, selectors, dep):
    """The public Beacon for "Try it yourself": address, last public beat and cooldown, read from the chain.

    None when this chain has no Beacon. The cooldown is read from the contract, not from config, because the
    owner can change it on chain with `setLimits`.
    """
    beacon = dep.get("beacon")
    if not beacon:
        return None
    calls = [("eth_call", [{"to": beacon, "data": selectors[sig]}, "latest"]) for sig in ("lastPublicBeat()", "cooldown()")]
    last, cooldown = (int(r, 16) for r in client.batch(chain["rpc"], calls))
    return {"chain": chain_name, "beacon": beacon.lower(), "last_beat_ts": last, "cooldown_seconds": cooldown}


def add_times(events, reader):
    """Adds `ts` (block timestamp) to each event; the page shows "last relight ... ago" from it."""
    reader.prefetch_times([e["block"] for e in events])
    for e in events:
        e["ts"] = reader.block_time(e["block"])
    return events


def last_reason(events, target):
    for e in reversed(events):
        if e.get("target") == target and e["event"] in ("GaveUp", "Skipped"):
            return f"{e['event']}: {e.get('reason', '?')} (tx {e['tx']})"
    return "no GaveUp/Skipped event yet"


def summarize_filters(result, topics, biller):
    """rnk_getFilters → counts of Omni-style contracts and of subscribers to the dark/lit topics."""
    zero = "0x" + "0" * 40
    omni = {}
    status_subs = {}
    watched = {topics[census.DARK], topics[census.LIT]}
    for flt in result.get("TopicFilters", []):
        topic0 = (flt.get("Topics") or [None])[0]
        source = (flt.get("Contract") or zero).lower()
        hears_status = (topic0 in watched and source in (biller.lower(), zero)) or (
            topic0 is None and source == biller.lower()
        )
        for cfg in flt.get("Configs") or []:
            if (cfg.get("RvmId") or zero).lower() != zero:
                continue
            addr = cfg["Contract"].lower()
            omni[addr] = omni.get(addr, False) or bool(cfg.get("Active"))
            if hears_status:
                status_subs[addr] = status_subs.get(addr, False) or bool(cfg.get("Active"))
    return {
        "filters": len(result.get("TopicFilters", [])),
        "omni_contracts": len(omni),
        "omni_contracts_all_inactive": sum(1 for a in omni.values() if not a),
        "status_topic_subscribers": len(status_subs),
        "status_topic_subscribers_active": sum(1 for a in status_subs.values() if a),
    }

