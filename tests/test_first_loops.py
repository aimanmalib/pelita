"""Offline tests for scripts/measure/first_loops.py on frozen fixture rows (shape of series.py record output)."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "measure"))
import first_loops  # noqa: E402

G, C = "0x" + "a" * 40, "0x" + "c" * 40


def row(side, role, n, **extra):
    r = {"side": side, "role": role, "target": G if role == "guarded" else C,
         "dark_tx": f"0xd{n}", "dark_block": 10 * n, "dark_ts": 1000 * n}
    r.update(extra)
    return r


def closed_lasna(n):
    return row("lasna", "guarded", n, reaction_tx=f"0xr{n}", reaction_block=10 * n + 1, reaction_ts=1000 * n + 2,
               reaction_fee_wei=5, outcome="Refueled", lit_tx=f"0xr{n}", lit_ts=1000 * n + 2, latency_s=2)


def closed_base(n):
    return row("base-sepolia", "guarded", n, reaction_tx=f"0xr{n}", reaction_block=7, reaction_ts=1000 * n + 3,
               reaction_fee_wei=5, outcome="RefuelRequested", callback_tx=f"0xc{n}", callback_ts=1000 * n + 6,
               callback_fee_wei=3, callback_event="Refueled", lit_tx=f"0xc{n}", lit_ts=1000 * n + 6, latency_s=6)


DEMO = {"beat_number": 4, "verdict": {"lit": True},
        "beat": {"tx": "0xb", "block": 1, "block_time": 100},
        "flicker_reaction": {"tx": "0xf", "block": 2, "block_time": 101, "refTx": "0xb"},
        "deliveries": [{"tx": "0xx", "block": 3, "block_time": 102, "status": 0},
                       {"tx": "0xy", "block": 4, "block_time": 103, "status": 1}]}


class FirstLoops(unittest.TestCase):
    def test_takes_the_earliest_closed_guarded_loop_and_keeps_reftx(self):
        lasna = {"side": "lasna", "rows": [row("lasna", "control", 1), row("lasna", "guarded", 2, outcome="GaveUp",
                                                                              reaction_tx="0xr2"),
                                           closed_lasna(3), closed_lasna(4)]}
        loop = first_loops.path_loop(lasna, destination=False)
        self.assertTrue(loop["closed"])
        self.assertEqual([s["step"] for s in loop["steps"]], ["dark", "reaction", "relit"])
        self.assertEqual(loop["steps"][0]["tx"], "0xd3")
        self.assertEqual(loop["steps"][1]["refTx"], loop["steps"][0]["tx"])

    def test_destination_needs_the_tank_refuel(self):
        no_cb = row("base-sepolia", "guarded", 1, reaction_tx="0xr1", reaction_block=1, reaction_ts=1,
                    outcome="RefuelRequested", callback_event="Skipped", callback_tx="0xc1", callback_ts=2,
                    lit_tx="0xl", lit_ts=3, latency_s=3)
        base = {"side": "base-sepolia", "rows": [no_cb, closed_base(2)]}
        loop = first_loops.path_loop(base, destination=True)
        self.assertEqual([s["step"] for s in loop["steps"]], ["dark", "reaction", "callback", "relit"])
        self.assertEqual(loop["steps"][2]["event"], "Refueled")
        self.assertEqual(loop["steps"][0]["tx"], "0xd2")

    def test_open_path_is_written_with_a_reason(self):
        loop = first_loops.path_loop({"side": "base-sepolia", "rows": []}, destination=True)
        self.assertEqual(loop, {"side": "base-sepolia", "closed": False, "reason": "no guarded outage yet"})
        loop = first_loops.path_loop({"side": "lasna", "rows": [row("lasna", "guarded", 1)]}, destination=False)
        self.assertFalse(loop["closed"])
        self.assertIn("no reaction", loop["reason"])

    def test_demo_uses_the_delivery_that_succeeded(self):
        loop = first_loops.demo_loop(DEMO)
        self.assertTrue(loop["closed"])
        self.assertEqual([s["tx"] for s in loop["steps"]], ["0xb", "0xf", "0xy"])
        self.assertEqual(loop["steps"][1]["refTx"], "0xb")

    def test_main_writes_file_and_exit_code_follows_all_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "E-005-series-lasna.json").write_text(json.dumps({"side": "lasna", "rows": [closed_lasna(1)]}))
            (p / "E-005-series-base-sepolia.json").write_text(json.dumps({"side": "base-sepolia", "rows": []}))
            (p / "E-004-demo-loop.json").write_text(json.dumps(DEMO))
            out = p / "out.json"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(first_loops.main(["--evidence", d, "--out", str(out)]), 1)
            self.assertFalse(json.loads(out.read_text())["all_closed"])
            (p / "E-005-series-base-sepolia.json").write_text(
                json.dumps({"side": "base-sepolia", "rows": [closed_base(1)]}))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(first_loops.main(["--evidence", d, "--out", str(out)]), 0)


if __name__ == "__main__":
    unittest.main()
