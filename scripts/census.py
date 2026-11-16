#!/usr/bin/env python3
"""Census of contracts that went dark for unpaid debt (read-only, no key).

Lasna: eth_getLogs on the system contract, in windows no wider than the RPC allows.
Destinations: the Blockscout logs API on the callback proxy (the public RPC caps eth_getLogs at a
few hundred blocks). A BlacklistContract log means "went dark", WhitelistContract means "lit again".

The summary is computed only from logs and block timestamps, never from the script's clock, so
running it twice over the same block range gives the same numbers (H8). ops/indexer.py calls the
same fetch and summarize functions, so the site and this script cannot disagree.

Usage: census.py [--chain NAME|all] [--from-block N] [--to-block N] [--out FILE]
"""

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import pelitarpc  # noqa: E402

DARK = "BlacklistContract(address)"
LIT = "WhitelistContract(address)"
BLOCKSCOUT_PAGE = 1000
PRUNED = ("not found", "pruned")  # Lasna: "block not found"; Base Sepolia: "pruned history unavailable"


def _int(value):
    return int(value, 16) if isinstance(value, str) else int(value)


def _topic_address(topic):
    return "0x" + topic[-40:].lower()


def windows(first, last, max_blocks):
    """Inclusive [from, to] ranges covering first..last, each at most max_blocks blocks."""
    out = []
    start = first
    while start <= last:
        end = min(last, start + max_blocks - 1)
        out.append((start, end))
        start = end + 1
    return out


class ChainReader:
    """Reads one chain for the census. `client` is a pelitarpc.Client."""

    def __init__(self, client, chain, topics):
        self.client = client
        self.chain = chain
        self.topics = topics
        self.kind_of = {topics[DARK]: "dark", topics[LIT]: "lit"}
        self._ts = {}

    def rpc(self, method, params=None):
        return self.client.call(self.chain["rpc"], method, params)

    def latest_block(self):
        """Newest block this reader trusts: the tip minus `index_lag_blocks` (Blockscout indexes behind the RPC)."""
        return _int(self.rpc("eth_blockNumber")) - int(self.chain.get("index_lag_blocks", 0))

    def prefetch_times(self, numbers, chunk=50):
        """Reads many block timestamps in JSON-RPC batches (Lasna logs carry no timestamp)."""
        todo = sorted({n for n in numbers if n not in self._ts})
        for i in range(0, len(todo), chunk):
            part = todo[i : i + chunk]
            blocks = self.client.batch(self.chain["rpc"], [("eth_getBlockByNumber", [hex(n), False]) for n in part])
            for n, block in zip(part, blocks):
                if block:
                    self._ts[n] = _int(block["timestamp"])

    def block_time(self, number):
        if number not in self._ts:
            block = self.rpc("eth_getBlockByNumber", [hex(number), False])
            if not block:
                raise pelitarpc.RpcError(f"block not found with number {hex(number)}")
            self._ts[number] = _int(block["timestamp"])
        return self._ts[number]

    def block_at(self, ts, latest):
        """First block whose timestamp is >= ts (binary search, about 25 reads).

        Both RPCs prune old blocks; a pruned block is older than any kept one, so it counts as before ts.
        """
        lo, hi = 0, latest
        while lo < hi:
            mid = (lo + hi) // 2
            try:
                before = self.block_time(mid) < ts
            except pelitarpc.RpcError as err:
                if not any(word in str(err) for word in PRUNED):
                    raise
                before = True
            if before:
                lo = mid + 1
            else:
                hi = mid
        return lo

    def _event(self, kind, address, block, log_index, tx, ts):
        return {"kind": kind, "address": address, "block": block, "log_index": log_index, "tx": tx, "ts": ts}

    def fetch(self, first, last):
        """All dark/lit events in [first, last], oldest first."""
        if self.chain.get("reactive"):
            events = self._fetch_rpc(first, last)
        else:
            events = self._fetch_blockscout(first, last)
        events.sort(key=lambda e: (e["block"], e["log_index"]))
        return events

    def _fetch_rpc(self, first, last):
        events = []
        topic_list = [self.topics[DARK], self.topics[LIT]]
        logs = []
        for lo, hi in windows(first, last, self.chain["get_logs_max_blocks"]):
            logs += self.rpc(
                "eth_getLogs",
                [{"address": self.chain["biller"], "topics": [topic_list], "fromBlock": hex(lo), "toBlock": hex(hi)}],
            )
        self.prefetch_times(_int(lg["blockNumber"]) for lg in logs if not _int(lg.get("blockTimestamp") or "0x0"))
        for log in logs:
            if log.get("removed"):
                continue
            block = _int(log["blockNumber"])
            ts = _int(log.get("blockTimestamp") or "0x0") or self.block_time(block)
            events.append(
                self._event(
                    self.kind_of[log["topics"][0]],
                    _topic_address(log["topics"][1]),
                    block,
                    _int(log["logIndex"]),
                    log["transactionHash"],
                    ts,
                )
            )
        return events

    def _fetch_blockscout(self, first, last):
        events = []
        for topic, kind in self.kind_of.items():
            page = 1
            while True:
                url = (
                    f"{self.chain['blockscout_api']}?module=logs&action=getLogs&address={self.chain['biller']}"
                    f"&topic0={topic}&fromBlock={first}&toBlock={last}&page={page}&offset={BLOCKSCOUT_PAGE}"
                )
                _, _, text = self.client.request(url)
                reply = json.loads(text)
                rows = reply.get("result") or []
                if reply.get("status") != "1" and rows:
                    raise pelitarpc.RpcError(f"blockscout: {reply.get('message')}")
                if not isinstance(rows, list):
                    raise pelitarpc.RpcError(f"blockscout: {rows}")
                for log in rows:
                    events.append(
                        self._event(
                            kind,
                            _topic_address(log["topics"][1]),
                            _int(log["blockNumber"]),
                            _int(log["logIndex"] if log["logIndex"] not in (None, "", "0x") else "0x0"),
                            log["transactionHash"],
                            _int(log["timeStamp"]),
                        )
                    )
                if len(rows) < BLOCKSCOUT_PAGE:
                    break
                page += 1
        return events


def _quantiles(values):
    if not values:
        return None
    values = sorted(values)
    return {
        "count": len(values),
        "min": values[0],
        "median": statistics.median(values),
        "max": values[-1],
    }


def summarize(events, as_of_ts):
    """Pairs dark/lit events per address in chain order. `as_of_ts` = timestamp of the last block read."""
    events = sorted(events, key=lambda e: (e["block"], e["log_index"]))
    open_since = {}
    outages_by = {}
    recoveries = []
    lit_without_dark = 0
    per_day = {}
    for e in events:
        addr = e["address"]
        if e["kind"] == "dark":
            outages_by[addr] = outages_by.get(addr, 0) + 1
            day = datetime.fromtimestamp(e["ts"], timezone.utc).strftime("%Y-%m-%d")
            per_day[day] = per_day.get(day, 0) + 1
            open_since.setdefault(addr, e)
        elif addr in open_since:
            recoveries.append(e["ts"] - open_since.pop(addr)["ts"])
        else:
            lit_without_dark += 1
    dark = sorted(
        (
            {
                "address": addr,
                "since_block": e["block"],
                "since_ts": e["ts"],
                "dark_seconds": max(0, as_of_ts - e["ts"]),
                "outages": outages_by[addr],
            }
            for addr, e in open_since.items()
        ),
        key=lambda d: (d["since_block"], d["address"]),
    )
    return {
        "outages": sum(outages_by.values()),
        "contracts": len(outages_by),
        "contracts_dark_twice_or_more": sum(1 for n in outages_by.values() if n >= 2),
        "recovered": len(recoveries),
        "lit_without_dark_in_range": lit_without_dark,
        "still_dark": len(dark),
        "recovery_seconds": _quantiles(recoveries),
        "dark_age_seconds": _quantiles([d["dark_seconds"] for d in dark]),
        "dark_per_day": dict(sorted(per_day.items())),
        "dark": dark,
    }


def census_result(chain, first, last, as_of, events):
    """The published census for one chain; shared with ops/indexer.py so both print the same numbers."""
    result = {
        "chain_id": chain["chain_id"],
        "source": "eth_getLogs" if chain.get("reactive") else "blockscout",
        "address": chain["biller"],
        "from_block": first,
        "to_block": last,
        "as_of_ts": as_of,
    }
    result.update(summarize(events, as_of))
    return result


def chain_census(reader, first, last):
    events = reader.fetch(first, last)
    return census_result(reader.chain, first, last, reader.block_time(last), events), events


def since_ts(pelita_cfg):
    stamp = pelita_cfg["census"]["since_utc"].replace("Z", "+00:00")
    return int(datetime.fromisoformat(stamp).timestamp())


def run(chains_cfg, pelita_cfg, client, names, from_block=None, to_block=None):
    out = {"since_utc": pelita_cfg["census"]["since_utc"], "chains": {}}
    for name in names:
        reader = ChainReader(client, chains_cfg["chains"][name], chains_cfg["topics"])
        last = to_block if to_block is not None else reader.latest_block()
        first = from_block if from_block is not None else reader.block_at(since_ts(pelita_cfg), last)
        out["chains"][name], _ = chain_census(reader, first, last)
    return out


def active_chains(chains_cfg):
    return [n for n, c in chains_cfg["chains"].items() if c.get("aktif")]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--chain", default="all")
    ap.add_argument("--from-block", type=int)
    ap.add_argument("--to-block", type=int)
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    chains_cfg = pelitarpc.load_config("chains.json")
    pelita_cfg = pelitarpc.load_config("pelita.json")
    names = active_chains(chains_cfg) if args.chain == "all" else [args.chain]
    if (args.from_block is not None or args.to_block is not None) and len(names) != 1:
        ap.error("--from-block/--to-block need a single --chain (block numbers differ per chain)")
    client = pelitarpc.Client(chains_cfg["user_agent"])
    result = run(chains_cfg, pelita_cfg, client, names, args.from_block, args.to_block)
    text = json.dumps(result, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
