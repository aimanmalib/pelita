"""Shape checks for config/chains.json and config/pelita.json (no network)."""

import json
import re
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
TOPIC = re.compile(r"^0x[0-9a-f]{64}$")
SELECTOR = re.compile(r"^0x[0-9a-f]{8}$")


def load(name):
    with open(ROOT / "config" / name, encoding="utf-8") as f:
        return json.load(f)


class ChainsConfigTest(unittest.TestCase):
    def setUp(self):
        self.cfg = load("chains.json")

    def test_user_agent_is_set(self):
        self.assertTrue(self.cfg["user_agent"].strip())
        self.assertNotIn("urllib", self.cfg["user_agent"].lower())

    def test_topics_and_selectors_are_well_formed(self):
        self.assertEqual(len(self.cfg["topics"]), 4)
        for value in self.cfg["topics"].values():
            self.assertRegex(value, TOPIC)
        for value in self.cfg["selectors"].values():
            self.assertRegex(value, SELECTOR)

    def test_every_chain_has_required_fields(self):
        for key, chain in self.cfg["chains"].items():
            with self.subTest(chain=key):
                for field in ("name", "chain_id", "aktif", "reactive", "rpc", "biller", "explorer"):
                    self.assertIn(field, chain)
                self.assertIsInstance(chain["chain_id"], int)
                self.assertIsInstance(chain["aktif"], bool)
                self.assertRegex(chain["biller"], ADDRESS)
                self.assertTrue(chain["rpc"].startswith("https://"))

    def test_exactly_one_active_reactive_chain_and_one_destination(self):
        active = [c for c in self.cfg["chains"].values() if c["aktif"]]
        self.assertEqual(sum(1 for c in active if c["reactive"]), 1)
        self.assertGreaterEqual(sum(1 for c in active if not c["reactive"]), 1)

    def test_chain_ids_are_unique(self):
        ids = [c["chain_id"] for c in self.cfg["chains"].values()]
        self.assertEqual(len(ids), len(set(ids)))


class PelitaConfigTest(unittest.TestCase):
    def setUp(self):
        self.cfg = load("pelita.json")
        self.chains = load("chains.json")["chains"]

    def test_amounts_are_positive_decimals(self):
        k = self.cfg["keeper"]
        self.assertGreater(Decimal(k["low_mark"]), Decimal(k["self_floor"]))
        for name, ward in self.cfg["wards"].items():
            with self.subTest(ward=name):
                self.assertTrue(1 <= ward["daily_cap"] <= 50)
                if "refill" in ward:
                    self.assertGreater(Decimal(ward["refill"]), 0)
                    self.assertLessEqual(Decimal(ward["refill"]), 1)
                    self.assertGreater(Decimal(ward["max_owed"]), 0)

    def test_destinations_refer_to_known_destination_chains(self):
        for name, dest in self.cfg["destinations"].items():
            with self.subTest(dest=name):
                self.assertIn(name, self.chains)
                self.assertFalse(self.chains[name]["reactive"])
                self.assertGreater(dest["callback_gas"], 0)
                self.assertGreaterEqual(Decimal(dest["tank_max_per_refuel"]), Decimal(self.cfg["wards"][name]["refill"]))

    def test_indexer_never_reads_filters_more_often_than_every_30_minutes(self):
        self.assertGreaterEqual(self.cfg["indexer"]["filters_interval_seconds"], 1800)


if __name__ == "__main__":
    unittest.main()


class DemoConfigTest(unittest.TestCase):
    """The demo unit tests use the same limits as config/pelita.json, so they test what will be deployed."""

    def test_demo_limits_are_sane(self):
        demo = load("pelita.json")["demo"]
        self.assertGreater(demo["beacon_max_beats_per_window"], 0)
        self.assertGreater(demo["beacon_window_seconds"], 0)
        self.assertGreaterEqual(demo["beacon_cooldown_seconds"], 0)
        self.assertGreater(demo["flicker_callback_gas"], 0)

    def test_demo_test_constants_match_config(self):
        demo = load("pelita.json")["demo"]
        source = (ROOT / "test" / "demo" / "Demo.t.sol").read_text(encoding="utf-8")
        consts = dict(re.findall(r"uint256 constant (COOLDOWN|MAX_BEATS|WINDOW) = (\d+);", source))
        self.assertEqual(int(consts["COOLDOWN"]), demo["beacon_cooldown_seconds"])
        self.assertEqual(int(consts["MAX_BEATS"]), demo["beacon_max_beats_per_window"])
        self.assertEqual(int(consts["WINDOW"]), demo["beacon_window_seconds"])
