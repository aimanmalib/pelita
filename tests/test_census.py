"""Offline tests for scripts/census.py over recorded Lasna logs and Base Sepolia Blockscout replies."""

import json
import statistics
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts"))
import census  # noqa: E402
import pelitarpc  # noqa: E402
from tests import fakechain  # noqa: E402

CHAINS = pelitarpc.load_config("chains.json")
CFG = pelitarpc.load_config("pelita.json")


def client(net):
    return pelitarpc.Client(CHAINS["user_agent"], opener=net.opener)


def ev(kind, addr, block, ts, idx=0):
    return {"kind": kind, "address": addr, "block": block, "log_index": idx, "tx": f"0x{block:x}{idx}", "ts": ts}


class WindowsTest(unittest.TestCase):
    def test_windows_cover_range_inclusively_without_overlap(self):
        self.assertEqual(census.windows(10, 14, 2), [(10, 11), (12, 13), (14, 14)])
        self.assertEqual(census.windows(5, 4, 30000), [])
        spans = census.windows(1, 100_000, 30000)
        self.assertTrue(all(hi - lo + 1 <= 30000 for lo, hi in spans))
        self.assertEqual(sum(hi - lo + 1 for lo, hi in spans), 100_000)


class SummarizeTest(unittest.TestCase):
    def test_pairs_dark_and_lit_per_address(self):
        a, b, c = "0x" + "a" * 40, "0x" + "b" * 40, "0x" + "c" * 40
        events = [
            ev("dark", a, 10, 1000),
            ev("lit", a, 12, 1060),
            ev("dark", a, 20, 2000),
            ev("dark", b, 21, 2100),
            ev("lit", c, 22, 2200),
        ]
        s = census.summarize(events, as_of_ts=5000)
        self.assertEqual(s["outages"], 3)
        self.assertEqual(s["contracts"], 2)
        self.assertEqual(s["contracts_dark_twice_or_more"], 1)
        self.assertEqual(s["recovered"], 1)
        self.assertEqual(s["recovery_seconds"]["median"], 60)
        self.assertEqual(s["lit_without_dark_in_range"], 1)
        self.assertEqual(s["still_dark"], 2)
        self.assertEqual([d["address"] for d in s["dark"]], [a, b])
        self.assertEqual(s["dark"][0]["dark_seconds"], 3000)
        self.assertEqual(sum(s["dark_per_day"].values()), 3)

    def test_order_of_input_does_not_matter(self):
        a = "0x" + "a" * 40
        events = [ev("lit", a, 12, 1060), ev("dark", a, 10, 1000)]
        self.assertEqual(census.summarize(events, 2000)["recovered"], 1)


class CensusOverRecordingTest(unittest.TestCase):
    def setUp(self):
        self.net = fakechain.FakeNet()
        self.fx = self.net.fx

    def test_lasna_reads_every_recorded_log_in_capped_windows(self):
        last = self.fx["lasna"]["latest"]
        first = last - 29999 - 5000
        out = census.run(CHAINS, CFG, client(self.net), ["lasna"], first, last)["chains"]["lasna"]
        recorded = self.fx["lasna"]["logs"]
        dark = sum(1 for lg in recorded if lg["topics"][0] == CHAINS["topics"][census.DARK])
        self.assertEqual(out["outages"], dark)
        self.assertEqual((out["from_block"], out["to_block"]), (first, last))
        cap = CHAINS["chains"]["lasna"]["get_logs_max_blocks"]
        for call in self.net.calls("eth_getLogs"):
            f = call["params"][0]
            self.assertLessEqual(int(f["toBlock"], 16) - int(f["fromBlock"], 16) + 1, cap)

    def test_base_sepolia_reads_blockscout_both_topics(self):
        last = self.fx["base-sepolia"]["latest"]
        out = census.run(CHAINS, CFG, client(self.net), ["base-sepolia"], 0, last)["chains"]["base-sepolia"]
        bs = self.fx["base-sepolia"]["blockscout"]
        self.assertEqual(out["outages"], len(bs[CHAINS["topics"][census.DARK]]))
        self.assertEqual(out["source"], "blockscout+eth_getLogs")
        self.assertTrue(self.net.calls("eth_getLogs") == [], "a long range goes to Blockscout")
        self.assertLessEqual(out["recovered"], len(bs[CHAINS["topics"][census.LIT]]))
        self.assertEqual(out["still_dark"], len(out["dark"]))

    def test_user_agent_is_always_sent(self):
        census.run(CHAINS, CFG, client(self.net), ["lasna", "base-sepolia"])
        self.assertGreater(len(self.net.requests), 2)
        for r in self.net.requests:
            self.assertEqual(r["headers"].get("user-agent"), CHAINS["user_agent"])

    def test_default_range_starts_at_since_and_ends_lag_blocks_behind_tip(self):
        out = census.run(CHAINS, CFG, client(self.net), ["base-sepolia"])["chains"]["base-sepolia"]
        lag = CHAINS["chains"]["base-sepolia"].get("index_lag_blocks", 0)
        self.assertEqual(out["to_block"], self.fx["base-sepolia"]["latest"] - lag)
        start = census.since_ts(CFG)
        self.assertGreaterEqual(self.net.block_ts("base-sepolia", out["from_block"]), start)
        self.assertLess(self.net.block_ts("base-sepolia", out["from_block"] - 1), start)

    def test_same_range_twice_gives_identical_output(self):
        args = (CHAINS, CFG, client(self.net), ["lasna"], self.fx["lasna"]["latest"] - 40000, self.fx["lasna"]["latest"])
        self.assertEqual(json.dumps(census.run(*args)), json.dumps(census.run(*args)))


class DebtTest(unittest.TestCase):
    """Each still-dark address carries the debt the biller reports at the last block read, plus the median."""

    def setUp(self):
        self.net = fakechain.FakeNet()
        self.last = self.net.fx["lasna"]["latest"]
        self.chain = CHAINS["chains"]["lasna"]

    def run_lasna(self):
        return census.run(CHAINS, CFG, client(self.net), ["lasna"], self.last - 40000, self.last)["chains"]["lasna"]

    def test_debt_per_dark_address_and_median(self):
        dark = [r["address"] for r in self.run_lasna()["dark"]]
        self.assertGreater(len(dark), 2)
        owed = {}
        for i, addr in enumerate(dark):
            owed[addr] = (i + 1) * 10**15
            data = CHAINS["selectors"]["debt(address)"] + addr[2:].rjust(64, "0")
            self.net.eth_calls[(self.chain["rpc"], self.chain["biller"].lower(), data)] = hex(owed[addr])
        out = self.run_lasna()
        for row in out["dark"]:
            self.assertEqual(row["debt_wei"], str(owed[row["address"]]))
        values = sorted(owed.values())
        self.assertEqual(out["debt_wei"]["count"], len(values))
        self.assertEqual(out["debt_wei"]["median"], str(int(statistics.median(values))))
        self.assertEqual(out["debt_wei"]["max"], str(values[-1]))
        block = {c["params"][1] for c in self.net.calls("eth_call")}
        self.assertEqual(block, {hex(self.last)})

    def test_unreadable_debt_leaves_census_without_debt_fields(self):
        real = self.net._rpc

        def broken(name, url, item):
            if item["method"] == "eth_call":
                return {"jsonrpc": "2.0", "id": item["id"], "error": {"message": "missing trie node"}}
            return real(name, url, item)

        self.net._rpc = broken
        out = self.run_lasna()
        self.assertGreater(out["still_dark"], 0)
        self.assertNotIn("debt_wei", out)
        self.assertFalse(any("debt_wei" in r for r in out["dark"]))


class BatchLimitTest(unittest.TestCase):
    """sepolia.base.org answers -32007 "25/second request limit reached" to one batch of 33 debt() calls
    (measured 27 Nov): batches follow the chain's rpc_batch_max with rpc_batch_pause_s between them."""

    def test_debt_batches_respect_chain_batch_limit_and_pause(self):
        net = fakechain.FakeNet()
        chain = CHAINS["chains"]["base-sepolia"]
        size, pause = chain["rpc_batch_max"], chain["rpc_batch_pause_s"]
        slept = []
        reader = census.ChainReader(client(net), chain, CHAINS["topics"], sleep=slept.append)
        addresses = [f"0x{i:040x}" for i in range(1, 2 * size + 6)]
        owed = reader.debts(addresses, 100, CHAINS["selectors"]["debt(address)"])
        self.assertEqual(len(owed), len(addresses))
        batches = [r["body"] for r in net.requests if isinstance(r["body"], list)]
        self.assertEqual([len(b) for b in batches], [size, size, 5])
        self.assertEqual(slept, [pause, pause])

    def test_timestamp_batches_respect_chain_batch_limit(self):
        net = fakechain.FakeNet()
        chain = CHAINS["chains"]["base-sepolia"]
        reader = census.ChainReader(client(net), chain, CHAINS["topics"], sleep=lambda s: None)
        last = net.fx["base-sepolia"]["latest"]
        reader.prefetch_times(range(last - chain["rpc_batch_max"] - 3, last))
        sizes = [len(r["body"]) for r in net.requests if isinstance(r["body"], list)]
        self.assertTrue(sizes and max(sizes) <= chain["rpc_batch_max"], sizes)


class PrunedHistoryTest(unittest.TestCase):
    def test_block_at_treats_pruned_blocks_as_older(self):
        for message in ("block not found with number {}", "pruned history unavailable: requested {}"):
            with self.subTest(message=message):
                self._pruned(message)

    def _pruned(self, message):
        net = fakechain.FakeNet()
        reader = census.ChainReader(client(net), CHAINS["chains"]["lasna"], CHAINS["topics"])
        real = reader.rpc
        floor = net.fx["lasna"]["latest"] - 2_000_000

        def pruned(method, params=None):
            if method == "eth_getBlockByNumber" and int(params[0], 16) < floor:
                raise pelitarpc.RpcError(message.format(int(params[0], 16)))
            return real(method, params)

        reader.rpc = pruned
        target = net.block_ts("lasna", floor + 1000)
        self.assertEqual(reader.block_at(target, net.fx["lasna"]["latest"]), floor + 1000)


if __name__ == "__main__":
    unittest.main()
