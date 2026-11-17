"""Offline tests for ops/indexer.py and ops/fleet.py (recorded chain data, temporary state folder)."""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "ops"))
import census  # noqa: E402
import fleet  # noqa: E402
import indexer  # noqa: E402
import pelitarpc  # noqa: E402
from tests import fakechain  # noqa: E402

CHAINS = pelitarpc.load_config("chains.json")
EVENTS = pelitarpc.load_config("events.json")
LASNA = CHAINS["chains"]["lasna"]
BASE = CHAINS["chains"]["base-sepolia"]
KEEPER = "0x" + "11" * 20
TANK = "0x" + "22" * 20
GUARDED = "0x" + "33" * 20
CONTROL = "0x" + "44" * 20


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class IndexerCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="pelita-idx-"))
        self.addCleanup(shutil.rmtree, self.root)
        shutil.copytree(ROOT / "config", self.root / "config")
        self.net = fakechain.FakeNet()
        self.clock = Clock(self.net.fx["lasna"]["clock"]["anchor_ts"] + 60)
        self.sent = []
        self.notify_rc = 0

    def notify(self, message, level):
        self.sent.append((level, message))
        return self.notify_rc

    def make(self):
        client = pelitarpc.Client(CHAINS["user_agent"], opener=self.net.opener)
        return indexer.Indexer(self.root, client, now=self.clock, notify=self.notify)

    def snapshot(self):
        return json.loads((self.root / "state" / "public" / "snapshot.json").read_text())

    def deploy(self):
        (self.root / "deployments").mkdir()
        lasna = {
            "chain_id": 5318007,
            "keeper": KEEPER,
            "deploy_block": self.net.latest["lasna"] - 10,
            "wards": [{"address": GUARDED, "role": "guarded", "name": "Lantern"}],
        }
        base = {
            "chain_id": 84532,
            "tank": TANK,
            "deploy_block": self.net.latest["base-sepolia"] - 400,
            "wards": [{"address": CONTROL, "role": "control", "name": "Lantern"}],
        }
        (self.root / "deployments" / "lasna.json").write_text(json.dumps(lasna))
        (self.root / "deployments" / "base-sepolia.json").write_text(json.dumps(base))

    def set_debt(self, chain, addr, wei):
        data = CHAINS["selectors"]["debt(address)"] + addr[2:].rjust(64, "0")
        self.net.eth_calls[(chain["rpc"], chain["biller"].lower(), data)] = hex(wei)


class SnapshotTest(IndexerCase):
    def test_first_run_writes_snapshot_with_census_per_active_chain(self):
        self.assertEqual(self.make().run(), 0)
        snap = self.snapshot()
        self.assertEqual(set(snap["census"]), {"lasna", "base-sepolia"})
        self.assertEqual(snap["fleet"], {})
        self.assertIsNotNone(snap["filters"]["summary"])
        self.assertFalse(list((self.root / "state" / "public").glob("*.tmp")))
        line = json.loads((self.root / "state" / "larian.jsonl").read_text().splitlines()[-1])
        self.assertTrue(line["ok"])

    def test_h8_incremental_runs_equal_one_census_over_the_same_range(self):
        self.net.latest["lasna"] -= 3000
        self.net.latest["base-sepolia"] -= 5000
        self.make().run()
        self.net.latest["lasna"] += 3000
        self.net.latest["base-sepolia"] += 5000
        self.clock.t += 120
        self.make().run()
        snap = self.snapshot()
        cfg = pelitarpc.load_config("pelita.json")
        fresh = fakechain.FakeNet()
        for name in ("lasna", "base-sepolia"):
            view = snap["census"][name]
            client = pelitarpc.Client(CHAINS["user_agent"], opener=fresh.opener)
            direct = census.run(CHAINS, cfg, client, [name], view["from_block"], view["to_block"])["chains"][name]
            self.assertEqual(view, direct, name)

    def test_rerun_without_new_blocks_does_not_duplicate_events(self):
        self.make().run()
        first = self.snapshot()["census"]
        self.clock.t += 120
        self.make().run()
        self.assertEqual(self.snapshot()["census"], first)

    def test_filters_are_read_at_most_every_interval(self):
        def count():
            return len(self.net.calls("rnk_getFilters"))

        self.make().run()
        self.clock.t += 120
        self.make().run()
        self.assertEqual(count(), 1)
        self.clock.t += pelitarpc.load_config("pelita.json")["indexer"]["filters_interval_seconds"]
        self.make().run()
        self.assertEqual(count(), 2)

    def test_user_agent_on_every_request(self):
        self.deploy()
        self.make().run()
        for r in self.net.requests:
            self.assertEqual(r["headers"].get("user-agent"), CHAINS["user_agent"])


class FailureTest(IndexerCase):
    def test_rpc_failure_keeps_old_snapshot_and_warns_once_after_limit(self):
        self.make().run()
        before = self.snapshot()
        self.net.fail = True
        limit = pelitarpc.load_config("pelita.json")["alerts"]["rpc_failures_before_warn"]
        calls_before = len(self.net.requests)
        for _ in range(limit + 3):
            self.clock.t += 120
            self.assertEqual(self.make().run(), 1)
        self.assertEqual(len(self.net.requests) - calls_before, limit + 3, "one request per run: no retry loop")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual([lvl for lvl, _ in self.sent], ["warn"])
        lines = (self.root / "state" / "larian.jsonl").read_text().splitlines()
        self.assertFalse(json.loads(lines[-1])["ok"])
        self.net.fail = False
        self.make().run()
        self.assertEqual(json.loads((self.root / "state" / "indexer.json").read_text())["failures"], 0)


class BlockscoutLimitTest(IndexerCase):
    """Blockscout's public API answered 429 to a call every 2 minutes (17 Nov); the indexer must not depend on it."""

    BEFORE_LAST_EVENT = 59709000  # between the recorded Base Sepolia events at 59704821 and 59711222

    def blockscout_calls(self):
        return [r for r in self.net.requests if r["url"].startswith(BASE["blockscout_api"])]

    def set_base_cursor(self, cursor):
        self.net.latest["base-sepolia"] = cursor + BASE["index_lag_blocks"]

    def test_steps_after_backfill_use_rpc_and_match_one_census(self):
        self.set_base_cursor(self.BEFORE_LAST_EVENT)
        self.assertEqual(self.make().run(), 0)
        self.net.blockscout_status = 429
        used = len(self.blockscout_calls())
        for _ in range(10):
            self.clock.t += 120
            self.net.latest["base-sepolia"] += 600
            self.assertEqual(self.make().run(), 0)
        self.assertEqual(len(self.blockscout_calls()), used, "2-minute steps never call Blockscout")
        view = self.snapshot()["census"]["base-sepolia"]
        self.assertNotIn("stale", view)
        self.assertEqual(view["to_block"], self.BEFORE_LAST_EVENT + 6000)
        cfg = pelitarpc.load_config("pelita.json")
        client = pelitarpc.Client(CHAINS["user_agent"], opener=fakechain.FakeNet().opener)
        direct = census.run(CHAINS, cfg, client, ["base-sepolia"], view["from_block"], view["to_block"])
        self.assertEqual(view, direct["chains"]["base-sepolia"])
        self.assertGreater(view["outages"], 0)
        runs = [json.loads(x) for x in (self.root / "state" / "larian.jsonl").read_text().splitlines()]
        self.assertTrue(all(r["ok"] and "stale" not in r for r in runs))

    def test_429_marks_only_that_census_stale_and_waits_before_retrying(self):
        self.net.blockscout_status = 429
        self.assertEqual(self.make().run(), 0, "a 429 does not fail the run")
        snap = self.snapshot()
        self.assertTrue(snap["census"]["base-sepolia"]["stale"])
        self.assertIn("429", snap["census"]["base-sepolia"]["error"])
        self.assertNotIn("stale", snap["census"]["lasna"])
        self.assertGreater(snap["census"]["lasna"]["outages"], 0)
        last = json.loads((self.root / "state" / "larian.jsonl").read_text().splitlines()[-1])
        self.assertEqual((last["ok"], last["stale"]), (True, ["base-sepolia"]))
        tried = len(self.blockscout_calls())
        self.clock.t += 120
        self.make().run()
        self.assertEqual(len(self.blockscout_calls()), tried, "no Blockscout call inside the retry wait")
        self.net.blockscout_status = 200
        self.clock.t += pelitarpc.load_config("pelita.json")["indexer"]["blockscout_retry_seconds"]
        self.make().run()
        view = self.snapshot()["census"]["base-sepolia"]
        self.assertNotIn("stale", view)
        self.assertGreater(view["outages"], 0)

    def test_stale_census_keeps_last_good_numbers(self):
        self.set_base_cursor(self.BEFORE_LAST_EVENT)
        self.make().run()
        good = self.snapshot()["census"]["base-sepolia"]
        self.net.blockscout_status = 429
        self.clock.t += 120
        self.net.latest["base-sepolia"] += 20000  # too far for the RPC windows: needs Blockscout
        self.assertEqual(self.make().run(), 0)
        view = self.snapshot()["census"]["base-sepolia"]
        self.assertTrue(view.pop("stale"))
        view.pop("stale_since"), view.pop("error")
        self.assertEqual(view, good)


class FleetTest(IndexerCase):
    def test_fleet_status_and_alert_kinds(self):
        self.deploy()
        self.net.balances[(LASNA["rpc"], KEEPER)] = 10**18  # 1 lREACT < low_mark 3
        self.net.balances[(BASE["rpc"], TANK)] = 10**18
        self.set_debt(LASNA, KEEPER, 5 * 10**15)
        self.set_debt(LASNA, GUARDED, 10**16)
        self.set_debt(BASE, CONTROL, 10**16)
        self.make().run()
        snap = self.snapshot()
        self.assertEqual(snap["fleet"]["lasna"]["own"]["role"], "keeper")
        self.assertEqual(snap["fleet"]["base-sepolia"]["wards"][0]["role"], "control")
        self.assertEqual(sorted(lvl for lvl, _ in self.sent), ["critical", "warn"])
        self.sent.clear()
        self.clock.t += 11 * 60
        self.make().run()
        dark = [m for _, m in self.sent]
        self.assertEqual(len(dark), 1, "guarded ward dark > 10 min; control ward never alerts")
        self.assertIn(GUARDED, dark[0])
        self.sent.clear()
        self.clock.t += 120
        self.make().run()
        self.assertEqual(self.sent, [], "at most once a day per kind")

    def test_failed_notify_is_retried_next_run(self):
        self.deploy()
        self.set_debt(LASNA, KEEPER, 1)
        self.net.balances[(LASNA["rpc"], KEEPER)] = 10 * 10**18
        self.net.balances[(BASE["rpc"], TANK)] = 10**18
        self.notify_rc = 1
        self.make().run()
        self.notify_rc = 0
        self.clock.t += 120
        self.make().run()
        self.assertEqual([lvl for lvl, _ in self.sent], ["critical", "critical"])

    def test_keeper_events_are_decoded_with_reason(self):
        self.deploy()
        topic = EVENTS["keeper"]["GaveUp(uint256,address,uint8)"]
        log = {
            "address": KEEPER,
            "topics": [topic, "0x" + hex(84532)[2:].rjust(64, "0"), "0x" + GUARDED[2:].rjust(64, "0")],
            "data": "0x" + "3".rjust(64, "0"),
            "blockNumber": hex(self.net.latest["lasna"] - 2),
            "logIndex": "0x0",
            "transactionHash": "0x" + "ab" * 32,
        }
        self.net.extra_logs[LASNA["rpc"]] = [log]
        self.make().run()
        events = self.snapshot()["events"]
        self.assertEqual(events[0]["event"], "GaveUp")
        self.assertEqual(events[0]["reason"], EVENTS["reasons"]["GaveUp"]["3"])
        self.assertIn("GaveUp", fleet.last_reason(events, GUARDED))
        self.assertEqual(events[0]["ts"], self.net.block_ts("lasna", self.net.latest["lasna"] - 2))

    def test_demo_reads_beacon_state_from_chain(self):
        self.make().run()
        self.assertIsNone(self.snapshot()["demo"], "no Beacon deployed yet: the page shows its pending text")
        self.deploy()
        beacon = "0x" + "5A" * 20
        dep = json.loads((self.root / "deployments" / "base-sepolia.json").read_text())
        dep["beacon"] = beacon
        (self.root / "deployments" / "base-sepolia.json").write_text(json.dumps(dep))
        sel = CHAINS["selectors"]
        self.net.eth_calls[(BASE["rpc"], beacon.lower(), sel["lastPublicBeat()"])] = hex(1_795_000_000)
        self.net.eth_calls[(BASE["rpc"], beacon.lower(), sel["cooldown()"])] = hex(900)
        self.clock.t += 120
        self.make().run()
        demo = self.snapshot()["demo"]
        self.assertEqual(
            demo,
            {"chain": "base-sepolia", "beacon": beacon.lower(), "last_beat_ts": 1_795_000_000, "cooldown_seconds": 900},
        )
        self.assertIn(demo["chain"], CHAINS["chains"])


class FiltersTest(unittest.TestCase):
    def test_summary_counts_omni_contracts_and_status_subscribers(self):
        fx = fakechain.load_fixture()["filters"]
        s = fleet.summarize_filters(fx, CHAINS["topics"], LASNA["biller"])
        self.assertEqual(s["filters"], len(fx["TopicFilters"]))
        self.assertGreater(s["omni_contracts"], 0)
        self.assertLessEqual(s["omni_contracts_all_inactive"], s["omni_contracts"])
        self.assertLessEqual(s["status_topic_subscribers_active"], s["status_topic_subscribers"])


class BeaconSelectorsTest(unittest.TestCase):
    def test_beacon_getters_read_by_the_indexer_exist_in_source(self):
        src = (ROOT / "src" / "demo" / "Beacon.sol").read_text()
        for sig in ("lastPublicBeat()", "cooldown()"):
            self.assertIn(sig, CHAINS["selectors"])
            self.assertRegex(src, rf"uint256 public {sig[:-2]};")


class EventsConfigTest(unittest.TestCase):
    def test_every_configured_signature_is_declared_in_source(self):
        import re

        declared = set()
        for path in (ROOT / "src").glob("**/*.sol"):
            text = re.sub(r"\s+", " ", path.read_text())
            for name, args in re.findall(r"event (\w+)\(([^)]*)\);", text):
                types = [a.strip().split(" ")[0] for a in args.split(",") if a.strip()]
                declared.add(f"{name}({','.join(types)})")
        for role in ("keeper", "tank", "demo"):
            for sig, topic in EVENTS[role].items():
                self.assertIn(sig, declared)
                self.assertRegex(topic, r"^0x[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
