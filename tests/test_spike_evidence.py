"""Offline tests for scripts/spike/spike_evidence.py (ADR 0002): log decoding, refTx pairing and the S1/S2 verdict."""

import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "spike"))
import spike_evidence as se  # noqa: E402

FLICKER = "0x" + "c8" * 20
KEEPER = "0x" + "fd" * 20
SYSTEM = "0x" + "88" * 20
TOPIC = {name: h for h, name in se.EVENTS.items()}


def pad(value):
    return "0x" + (value[2:] if isinstance(value, str) else format(value, "x")).rjust(64, "0")


def log(address, name, *topics, data="0x", index=0):
    return {"address": address, "topics": [TOPIC[name], *[pad(t) for t in topics]], "data": data,
            "logIndex": hex(index)}


def receipt(tx, block, logs, ref=None):
    r = {"transactionHash": tx, "blockNumber": hex(block), "status": "0x1", "from": SYSTEM, "to": SYSTEM,
         "gasUsed": hex(100), "logs": logs, "rnkTxType": "r"}
    if ref:
        r["refTx"], r["refChainId"] = ref, hex(84532)
    return r


def refueled_data(amount, owed, origin):
    return "0x" + "".join(format(v, "x").rjust(64, "0") for v in (amount, owed, origin))


FLICKER_RX = receipt("0xf1", 10, [log(FLICKER, "Forwarded", 1, data=pad(5)),
                                  log(SYSTEM, "BlacklistContract", FLICKER, index=1)], ref="0xbeat")


def keeper_rx(*names):
    built = {"WentDark": log(KEEPER, "WentDark", 5318007, FLICKER, data=pad(10)),
             "WhitelistContract": log(SYSTEM, "WhitelistContract", FLICKER, index=1),
             "Refueled": log(KEEPER, "Refueled", 5318007, FLICKER, data=refueled_data(65, 15, 10), index=2)}
    return receipt("0xk1", 11, [built[n] for n in names], ref="0xf1")


class SpikeEvidenceTest(unittest.TestCase):
    def test_summarise_decodes_named_events(self):
        s = se.summarise(keeper_rx("WentDark", "WhitelistContract", "Refueled"), 1000)
        self.assertEqual([lg["event"] for lg in s["logs"]], ["WentDark", "WhitelistContract", "Refueled"])
        ref = s["logs"][2]
        self.assertEqual((ref["target"], ref["amount_wei"], ref["owed_wei"], ref["origin_block"]), (FLICKER, 65, 15, 10))
        self.assertEqual(s["logs"][1]["contract"], FLICKER)
        self.assertEqual((s["refTx"], s["refChainId"], s["block"], s["block_time"]), ("0xf1", 84532, 11, 1000))

    def test_find_reaction_matches_ref_tx_only(self):
        rx = [receipt("0xa", 1, [], ref="0xother"), FLICKER_RX]
        self.assertIs(se.find_reaction(rx, "0xBEAT"), FLICKER_RX)
        self.assertIsNone(se.find_reaction(rx, "0xnone"))

    def test_verdict_both_hold(self):
        fl = se.summarise(FLICKER_RX, 1)
        kp = se.summarise(keeper_rx("WentDark", "WhitelistContract", "Refueled"), 2)
        self.assertEqual(se.verdict(FLICKER, kp, fl, 0), {"S1": True, "S2": True})

    def test_s2_fails_without_whitelist_in_same_tx_or_with_debt_left(self):
        fl = se.summarise(FLICKER_RX, 1)
        no_white = se.summarise(keeper_rx("WentDark", "Refueled"), 2)
        self.assertEqual(se.verdict(FLICKER, no_white, fl, 0), {"S1": True, "S2": False})
        full = se.summarise(keeper_rx("WentDark", "WhitelistContract", "Refueled"), 2)
        self.assertFalse(se.verdict(FLICKER, full, fl, 1)["S2"])

    def test_s1_fails_without_keeper_reaction(self):
        self.assertEqual(se.verdict(FLICKER, None, se.summarise(FLICKER_RX, 1), 0), {"S1": False, "S2": False})

    def test_topic_constants_match_signatures(self):
        self.assertEqual(set(se.EVENTS.values()), set(se.SIGS))
        cast = shutil.which("cast") or str(Path.home() / ".foundry" / "bin" / "cast")
        if not Path(cast).exists():
            self.skipTest("cast not installed")
        for h, name in se.EVENTS.items():
            out = subprocess.run([cast, "keccak", se.SIGS[name]], capture_output=True, text=True, check=True)
            self.assertEqual(out.stdout.strip(), h, name)


if __name__ == "__main__":
    unittest.main()
