"""The public Base Sepolia RPC answered HTTP 429 to a third of the indexer runs (23-24 Nov, ADR 0004).

One chain that refuses must not throw away the whole run: that chain keeps its last good view marked
`stale`, the other chains stay fresh, the client tries the chain's `rpc_fallback` once, and the warning
names the chain and the host that refused.
"""

import json
import unittest

from tests import fakechain
from tests.test_indexer import BASE, CHAINS, KEEPER, LASNA, TANK, IndexerCase, indexer, pelitarpc

FALLBACK = "https://base-fallback.test"  # test-only endpoint; the real list lives in config/chains.json


class RpcLimitCase(IndexerCase):
    def setUp(self):
        super().setUp()
        self.limit = pelitarpc.load_config("pelita.json")["alerts"]["rpc_failures_before_warn"]

    def chains(self):
        return json.loads((self.root / "config" / "chains.json").read_text())

    def set_base_fallback(self, urls):
        cfg = self.chains()
        cfg["chains"]["base-sepolia"]["rpc_fallback"] = urls
        (self.root / "config" / "chains.json").write_text(json.dumps(cfg))
        for url in urls:
            self.net.by_rpc[url] = "base-sepolia"

    def make(self):
        client = pelitarpc.client_for(self.chains(), opener=self.net.opener)
        return indexer.Indexer(self.root, client, now=self.clock, notify=self.notify)

    def limit_base(self, status=429):
        for url in [BASE["rpc"]] + self.chains()["chains"]["base-sepolia"].get("rpc_fallback", []):
            self.net.limited[url] = status

    def runs(self):
        return [json.loads(x) for x in (self.root / "state" / "larian.jsonl").read_text().splitlines()]

    def state(self):
        return json.loads((self.root / "state" / "indexer.json").read_text())


class OneChainRefusesTest(RpcLimitCase):
    def test_base_429_keeps_the_run_and_marks_only_base_stale(self):
        self.deploy()
        self.net.balances[(LASNA["rpc"], KEEPER)] = 10 * 10**18
        self.net.balances[(BASE["rpc"], TANK)] = 10**18
        self.assertEqual(self.make().run(), 0)
        good = self.snapshot()
        self.limit_base()
        self.clock.t += 120
        self.net.latest["lasna"] += 50
        self.assertEqual(self.make().run(), 0, "a 429 on one chain does not fail the run")
        snap = self.snapshot()
        self.assertGreater(snap["generated_at"], good["generated_at"], "snapshot written")
        self.assertTrue(snap["census"]["base-sepolia"]["stale"])
        self.assertIn("429", snap["census"]["base-sepolia"]["error"])
        self.assertTrue(snap["fleet"]["base-sepolia"]["stale"])
        self.assertEqual(snap["fleet"]["base-sepolia"]["wards"], good["fleet"]["base-sepolia"]["wards"])
        self.assertNotIn("stale", snap["census"]["lasna"])
        self.assertNotIn("stale", snap["fleet"]["lasna"])
        self.assertEqual(snap["census"]["lasna"]["to_block"], self.net.latest["lasna"] - LASNA.get("index_lag_blocks", 0))
        last = self.runs()[-1]
        self.assertTrue(last["ok"])
        self.assertEqual(last["stale"], ["base-sepolia"])
        self.assertIn("base-sepolia", last["chain_errors"])
        self.assertEqual(self.state()["failures"], 0)
        self.assertEqual(self.sent, [])

    def test_stale_fleet_view_raises_no_fleet_alert(self):
        self.deploy()
        self.net.balances[(LASNA["rpc"], KEEPER)] = 10 * 10**18
        self.net.balances[(BASE["rpc"], TANK)] = 10**30
        self.make().run()
        self.limit_base()
        for _ in range(3):
            self.clock.t += 120
            self.make().run()
        self.assertEqual(self.sent, [])

    def test_every_chain_down_still_fails_the_run_and_keeps_the_snapshot(self):
        self.make().run()
        before = self.snapshot()
        self.net.fail = True
        self.clock.t += 120
        self.assertEqual(self.make().run(), 1)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.runs()[-1]["ok"])
        self.assertEqual(self.state()["failures"], 1)


class FallbackTest(RpcLimitCase):
    def test_429_on_primary_reads_through_the_fallback(self):
        self.set_base_fallback([FALLBACK])
        self.net.limited[BASE["rpc"]] = 429
        self.assertEqual(self.make().run(), 0)
        snap = self.snapshot()
        self.assertNotIn("stale", snap["census"]["base-sepolia"])
        self.assertNotIn("chain_errors", self.runs()[-1])
        primary = [r for r in self.net.requests if r["url"] == BASE["rpc"]]
        self.assertEqual(len(primary), 1, "after one refusal the run stays on the fallback")
        self.assertTrue(any(r["url"] == FALLBACK for r in self.net.requests))

    def test_each_endpoint_is_tried_once_per_call_and_the_error_names_every_host(self):
        self.set_base_fallback([FALLBACK])
        self.limit_base()
        client = pelitarpc.client_for(self.chains(), opener=self.net.opener)
        with self.assertRaises(pelitarpc.Unavailable) as caught:
            client.call(BASE["rpc"], "eth_blockNumber")
        self.assertNotIsInstance(caught.exception, pelitarpc.RpcError, "census.debts() turns RpcError into a dash")
        self.assertEqual([r["url"] for r in self.net.requests], [BASE["rpc"], FALLBACK], "no retry loop")
        self.assertIn("sepolia.base.org", str(caught.exception))
        self.assertIn("base-fallback.test", str(caught.exception))
        self.assertIn("429", str(caught.exception))

    def test_request_limit_reply_moves_to_the_fallback(self):
        """Lasna once answered -32007 '25/second request limit' inside a 200 reply (24 Nov)."""
        replies = []

        def opener(req, timeout=None):
            replies.append(req.full_url)
            if req.full_url == BASE["rpc"]:
                return fakechain._Resp({"jsonrpc": "2.0", "id": 1, "error": {"code": -32007, "message": "25/second request limit reached"}})
            return self.net.opener(req, timeout)

        self.set_base_fallback([FALLBACK])
        client = pelitarpc.client_for(self.chains(), opener=opener)
        self.assertEqual(int(client.call(BASE["rpc"], "eth_blockNumber"), 16), self.net.latest["base-sepolia"])
        self.assertEqual(replies, [BASE["rpc"], FALLBACK])

    def test_a_node_error_does_not_move_to_the_fallback(self):
        def opener(req, timeout=None):
            self.net.requests.append({"url": req.full_url})
            return fakechain._Resp({"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "header not found"}})

        self.set_base_fallback([FALLBACK])
        client = pelitarpc.client_for(self.chains(), opener=opener)
        with self.assertRaises(pelitarpc.RpcError) as caught:
            client.call(BASE["rpc"], "eth_getBlockByNumber", ["0x1", False])
        self.assertIn("header not found", str(caught.exception))
        self.assertEqual(len(self.net.requests), 1)

    def test_shipped_fallbacks_are_other_https_endpoints(self):
        for name, chain in CHAINS["chains"].items():
            for url in chain.get("rpc_fallback", []):
                self.assertTrue(url.startswith("https://"), name)
                self.assertNotEqual(url, chain["rpc"], name)
        self.assertTrue(CHAINS["chains"]["base-sepolia"].get("rpc_fallback"), "Base Sepolia has a fallback (ADR 0004)")


class ChainWarningTest(RpcLimitCase):
    def test_one_warning_after_the_limit_naming_chain_and_host(self):
        self.make().run()
        self.limit_base()
        for _ in range(self.limit + 3):
            self.clock.t += 120
            self.assertEqual(self.make().run(), 0)
        self.assertEqual([lvl for lvl, _ in self.sent], ["warn"])
        text = self.sent[0][1]
        self.assertIn("base-sepolia sepolia.base.org", text)
        self.assertIn("429", text)
        self.assertEqual(self.state()["chain_stale"]["base-sepolia"]["runs"], self.limit + 3)
        self.net.limited.clear()
        self.clock.t += 120
        self.make().run()
        self.assertNotIn("base-sepolia", self.state()["chain_stale"])
        self.assertNotIn("stale", self.snapshot()["census"]["base-sepolia"])


if __name__ == "__main__":
    unittest.main()
