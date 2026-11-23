"""Offline tests for scripts/spike/demo_loop_evidence.py (P2c): beat -> Flicker -> proxy delivery -> Lit, read back."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "spike"))
import demo_loop_evidence as dl  # noqa: E402

EVENTS_CFG = json.loads((ROOT / "config" / "events.json").read_text(encoding="utf-8"))
BEAT = EVENTS_CFG["demo"]["Beat(uint256,uint256)"]
LIT = EVENTS_CFG["demo"]["Lit(uint256,uint256,uint256)"]
FLICKER = "0x" + "c8" * 20
LANTERN = "0x" + "1a" * 20
PROXY = "0x" + "47" * 20
SYSTEM = "0x" + "88" * 20
SENDER = "0x" + "f7" * 20
OPERATOR = "0x" + "d0" * 20
BEAT_BLOCK, N = 1000, 2
DEPS = {"lasna": {"contracts": {"flicker_guarded": {"address": FLICKER, "block": 10}}},
        "base-sepolia": {"contracts": {"lantern_guarded": {"address": LANTERN}}}}


def w(v):
    return dl.word(int(v, 16) if isinstance(v, str) else v)


def delivery_input(n=N, origin=BEAT_BLOCK, lantern=LANTERN, flicker=FLICKER):
    payload = "9849eba3" + w(flicker) + w(n) + w(origin)
    return "0x8d1f0fa1" + w(0) + w(0x40) + w(84532) + w(lantern) + w(100000) + w(0x80) + payload


def rcpt(tx, block, logs, status=1, ref=None, to=PROXY):
    r = {"transactionHash": tx, "blockNumber": hex(block), "status": hex(status), "from": SENDER, "to": to,
         "gasUsed": hex(21000), "logs": logs}
    if ref:
        r.update(refTx=ref, refChainId=hex(84532), rnkTxType="r")
    return r


def lg(address, *topics, data="0x"):
    return {"address": address, "topics": list(topics), "data": data, "logIndex": "0x0"}


class FakeRpc:
    def __init__(self, head, blocks=None, revert="0xea8e4eb5"):
        self.head, self.blocks, self.revert, self.batches = head, blocks or {}, revert, []

    def call(self, url, method, params=None):
        assert method == "eth_blockNumber"
        return hex(self.head)

    def batch(self, url, calls):
        self.batches.append(len(calls))
        return [{"transactions": self.blocks.get(int(p[0], 16), [])} for _, p in calls]

    def request(self, url, body):
        return 200, {}, json.dumps({"jsonrpc": "2.0", "id": 1, "error": {"code": 3, "data": self.revert}})


class FakeChain:
    def __init__(self, rpc, receipts=None, ts=lambda b: 1_000_000 + 2 * b, reactions=()):
        self.c, self.url, self.receipts, self.ts, self._rx = rpc, "u", receipts or {}, ts, list(reactions)

    def receipt(self, tx):
        return self.receipts[tx]

    def block_time(self, number_hex):
        return self.ts(int(number_hex, 16))

    def reactions(self, start, end, step=50):
        return [r for r in self._rx if start <= int(r["blockNumber"], 16) <= end]


def chains(delivered=True, operator_tx=True):
    beat = rcpt("0xbeat", BEAT_BLOCK, [lg("0x" + "90" * 20, BEAT, w(N), data="0x" + w(5))], to="0x" + "90" * 20)
    flicker_rx = rcpt("0xfl", 40, [lg(SYSTEM, dl.CALLBACK_REQUEST, "0x" + w(84532), "0x" + w(FLICKER), "0x" + w(LANTERN)),
                                   lg(FLICKER, "0x509da02d76b66d8370a76a9ed0b42a3de167a8a53d97b435f51441a53d557a4d",
                                      "0x" + w(N))], ref="0xbeat")
    lit_logs = [lg(LANTERN, LIT, "0x" + w(N))] if delivered else []
    blocks = {BEAT_BLOCK + 4: [{"hash": "0xdel", "blockNumber": hex(BEAT_BLOCK + 4), "from": SENDER, "to": PROXY,
                                "input": delivery_input()},
                               {"hash": "0xelse", "blockNumber": hex(BEAT_BLOCK + 4), "from": SENDER, "to": PROXY,
                                "input": delivery_input(n=N + 1)},
                               {"hash": "0xnot", "blockNumber": hex(BEAT_BLOCK + 4), "from": SENDER, "to": LANTERN,
                                "input": delivery_input()}]}
    if operator_tx:
        blocks[BEAT_BLOCK - 6] = [{"hash": "0xop", "blockNumber": hex(BEAT_BLOCK - 6), "from": OPERATOR, "to": PROXY,
                                   "input": "0xe69cc4f0" + w(0x20)}]
    base = FakeChain(FakeRpc(BEAT_BLOCK + 500, blocks),
                     {"0xbeat": beat, "0xdel": rcpt("0xdel", BEAT_BLOCK + 4, lit_logs, status=1 if delivered else 0)})
    # Lasna clock: block b at 1_000_000 + b, so the beat (base ts 1_002_000) maps to Lasna block 2000.
    lasna = FakeChain(FakeRpc(5000), ts=lambda b: 1_000_000 + b, reactions=[dict(flicker_rx, blockNumber=hex(2010))])
    return lasna, base


def run(**kw):
    lasna, base = chains(**kw)
    return dl.collect(lasna, base, DEPS, PROXY, EVENTS_CFG, "0xbeat", base_blocks=20, lasna_blocks=60, rate=(7, 0.0))


class DemoLoopEvidenceTest(unittest.TestCase):
    def test_carries_needs_this_lantern_beat_number_and_origin_block(self):
        self.assertTrue(dl.carries(delivery_input(), LANTERN, FLICKER, N, BEAT_BLOCK))
        self.assertFalse(dl.carries(delivery_input(n=N + 1), LANTERN, FLICKER, N, BEAT_BLOCK))
        self.assertFalse(dl.carries(delivery_input(origin=BEAT_BLOCK - 1), LANTERN, FLICKER, N, BEAT_BLOCK))
        self.assertFalse(dl.carries(delivery_input(lantern="0x" + "ab" * 20), LANTERN, FLICKER, N, BEAT_BLOCK))
        self.assertFalse(dl.carries(None, LANTERN, FLICKER, N, BEAT_BLOCK))

    def test_block_at_finds_last_block_not_after_timestamp(self):
        chain = FakeChain(FakeRpc(0), ts=lambda b: 100 + 3 * b)
        self.assertEqual(dl.block_at(chain, 100 + 3 * 57 + 2, 0, 500), 57)
        self.assertEqual(dl.block_at(chain, 50, 0, 500), 0)

    def test_full_loop_is_lit(self):
        ev = run()
        self.assertEqual(ev["verdict"], {"forwarded": True, "delivered": True, "lit": True})
        self.assertEqual([d["tx"] for d in ev["deliveries"]], ["0xdel"])
        self.assertEqual(ev["flicker_reaction"]["refTx"], "0xbeat")
        self.assertEqual(ev["beat_number"], N)

    def test_reaction_in_first_block_of_the_beat_second_and_not_a_retired_flicker(self):
        """23 Nov: the reaction sat in the first of several Lasna blocks sharing the beat's second, after the reaction of a
        retired Flicker to the same beat. Both were missed / mixed up by the old reader."""
        lasna, base = chains()
        good = lasna._rx[0]
        retired = dict(good, transactionHash="0xold", logs=[lg(SYSTEM, dl.CALLBACK_REQUEST, "0x" + w(84532),
                                                               "0x" + w("0x" + "0d" * 20), "0x" + w("0x" + "0e" * 20)),
                                                            lg("0x" + "0d" * 20, "0x" + w(1))])
        # Two Lasna blocks a second; the beat second (base ts 1_002_000) spans blocks 4000..4001.
        lasna.ts = lambda b: 1_000_000 + b // 2
        lasna._rx = [dict(retired, blockNumber=hex(4000)), dict(good, blockNumber=hex(4000))]
        ev = dl.collect(lasna, base, DEPS, PROXY, EVENTS_CFG, "0xbeat", base_blocks=20, lasna_blocks=60, rate=(7, 0.0))
        self.assertEqual(ev["flicker_reaction"]["tx"], "0xfl")
        self.assertTrue(ev["verdict"]["forwarded"])

    def test_reverted_delivery_keeps_revert_data_and_operator_change_in_window(self):
        ev = run(delivered=False)
        self.assertEqual(ev["verdict"], {"forwarded": True, "delivered": False, "lit": False})
        self.assertEqual((ev["deliveries"][0]["status"], ev["deliveries"][0]["revert_data"]), (0, "0xea8e4eb5"))
        others = {o["tx"]: o["call"] for o in ev["other_proxy_txs"]}
        self.assertEqual(others, {"0xop": "removeCallbackSenders", "0xelse": "deliverCallback"})
        self.assertEqual(ev["window"]["base_blocks"], [BEAT_BLOCK - 30, BEAT_BLOCK + 20])

    def test_proxy_scan_is_batched_and_paced(self):
        rpc, slept = FakeRpc(0), []
        dl.proxy_txs(FakeChain(rpc), PROXY, 0, 49, 20, 1.1, sleep=slept.append)
        self.assertEqual(rpc.batches, [20, 20, 10])
        self.assertEqual(slept, [1.1, 1.1])

    def test_rate_config_present_for_base(self):
        base = json.loads((ROOT / "config" / "chains.json").read_text(encoding="utf-8"))["chains"]["base-sepolia"]
        self.assertGreater(base["rpc_batch_max"], 0)
        self.assertLessEqual(base["rpc_batch_max"], 25)
        self.assertGreater(base["rpc_batch_pause_s"], 1.0)


if __name__ == "__main__":
    unittest.main()
