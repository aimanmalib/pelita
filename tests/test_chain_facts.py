"""Offline tests for scripts/spike/chain_facts.py and scripts/lib/pelitarpc.py (recorded fixture, no network)."""

import copy
import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts" / "spike"))
import chain_facts  # noqa: E402
import pelitarpc  # noqa: E402


def fixture():
    with open(ROOT / "tests" / "fixtures" / "chain_facts_readings.json", encoding="utf-8") as f:
        return json.load(f)


def frozen_config():
    """The config as it was when the fixture was recorded: the readings themselves define it."""
    cfg = pelitarpc.load_config("chains.json")
    fx = fixture()
    cfg = copy.deepcopy(cfg)
    for name, chain in cfg["chains"].items():
        r = fx["readings"]["chains"][name]
        chain["chain_id"] = r["chain_id"]["value"]
        for key in chain_facts.FEE_GETTERS:
            chain["fees"][key] = r["fee_" + key]["value"]
    return cfg, fx


class JudgeTest(unittest.TestCase):
    def setUp(self):
        self.cfg, self.fx = frozen_config()

    def judge(self, cfg=None, readings=None):
        return chain_facts.judge(cfg or self.cfg, readings or self.fx["readings"], self.fx["constants"])

    def test_recorded_readings_agree_with_config(self):
        bad = [c for c in self.judge() if not c["ok"]]
        self.assertEqual(bad, [])

    def test_every_config_topic_and_selector_is_checked(self):
        names = {c["check"] for c in self.judge()}
        for sig in self.cfg["topics"]:
            self.assertIn(f"topic {sig}", names)
        self.assertIn("trigger selector on the newest blacklisting", names)

    def test_wrong_fee_in_config_is_caught(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["chains"]["lasna"]["fees"]["extra_gas"] += 1
        bad = [c["check"] for c in self.judge(cfg) if not c["ok"]]
        self.assertEqual(bad, ["lasna fee extra_gas"])

    def test_wrong_topic_in_config_is_caught(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["topics"]["WhitelistContract(address)"] = "0x" + "0" * 64
        bad = [c["check"] for c in self.judge(cfg) if not c["ok"]]
        self.assertIn("topic WhitelistContract(address)", bad)

    def test_logs_cap_that_is_too_low_is_caught(self):
        readings = copy.deepcopy(self.fx["readings"])
        readings["chains"]["base-sepolia"]["logs_over_cap"] = {"ok": True, "value": 0}
        bad = [c["check"] for c in self.judge(readings=readings) if not c["ok"]]
        self.assertEqual(bad, ["base-sepolia eth_getLogs one block over the cap refused"])

    def test_failed_reading_is_a_failed_check_not_a_crash(self):
        readings = copy.deepcopy(self.fx["readings"])
        readings["chains"]["lasna"]["chain_id"] = {"ok": False, "error": "URLError: timed out"}
        bad = [c["check"] for c in self.judge(readings=readings) if not c["ok"]]
        self.assertEqual(bad, ["lasna chain_id"])

    def test_s1_reaction_must_point_back_to_the_blacklisting(self):
        readings = copy.deepcopy(self.fx["readings"])
        readings["lasna_extras"]["s1_pairs"][0]["refTx"] = "0x" + "1" * 64
        bad = [c["check"] for c in self.judge(readings=readings) if not c["ok"]]
        self.assertEqual(len(bad), 1)
        self.assertTrue(bad[0].startswith("S1 reaction"))

    def test_s1_pairs_in_config_are_the_ones_recorded(self):
        cfg = pelitarpc.load_config("chains.json")
        recorded = [(p["blacklisting"], p["reaction"]) for p in self.fx["readings"]["lasna_extras"]["s1_pairs"]]
        self.assertEqual([(p["blacklisting"], p["reaction"]) for p in cfg["s1_observed_pairs"]], recorded)


class FakeResponse(io.BytesIO):
    status = 200
    headers = {"Access-Control-Allow-Origin": "x"}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class ClientTest(unittest.TestCase):
    def setUp(self):
        self.sent = []

    def opener(self, reply):
        def _open(req, timeout):
            self.sent.append(req)
            return FakeResponse(json.dumps(reply).encode())

        return _open

    def test_user_agent_from_config_is_always_sent(self):
        ua = pelitarpc.load_config("chains.json")["user_agent"]
        c = pelitarpc.Client(ua, opener=self.opener({"jsonrpc": "2.0", "id": 1, "result": "0x1"}))
        c.call("https://rpc.invalid/", "eth_chainId")
        c.request("https://explorer.invalid/api")
        self.assertEqual([r.get_header("User-agent") for r in self.sent], [ua, ua])

    def test_missing_user_agent_is_refused(self):
        with self.assertRaises(ValueError):
            pelitarpc.Client("  ")

    def test_error_reply_raises_with_node_message(self):
        c = pelitarpc.Client("t/1", opener=self.opener({"jsonrpc": "2.0", "id": 1, "error": {"message": "range too large"}}))
        with self.assertRaisesRegex(pelitarpc.RpcError, "range too large"):
            c.call("https://rpc.invalid/", "eth_getLogs", [{}])

    def test_headers_are_lower_cased(self):
        c = pelitarpc.Client("t/1", opener=self.opener({}))
        _, head, _ = c.request("https://rpc.invalid/", {"x": 1})
        self.assertIn("access-control-allow-origin", head)


if __name__ == "__main__":
    unittest.main()
