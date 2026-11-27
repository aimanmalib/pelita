"""Offline tests for scripts/measure/series.py (pairing) and report.py (docs/measured.md) on frozen fixtures."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "measure"))
import report  # noqa: E402
import series  # noqa: E402

CHAINS = series.pelitarpc.load_config("chains.json")
G, C = "0x" + "a" * 40, "0x" + "c" * 40


def dark(addr, block, ts, tx):
    return {"address": addr, "block": block, "log_index": 0, "tx": tx, "ts": ts}


def lit(addr, block, ts, tx):
    return {"address": addr, "block": block, "tx": tx, "ts": ts}


def lasna_rows():
    darks = [dark(G, 10, 1000, "0xd1"), dark(C, 11, 1001, "0xd2"), dark(G, 20, 2000, "0xd3")]
    lits = [lit(G, 11, 1002, "0xl1")]
    reactions = [
        {"event": "Refueled", "target": G, "tx": "0xr1", "block": 11, "ts": 1002, "ref_tx": "0xD1", "fee_wei": 7},
        {"event": "GaveUp", "target": G, "tx": "0xr3", "block": 21, "ts": 2001, "ref_tx": "0xd3", "fee_wei": 9,
         "reason": "daily cap reached"},
        # Same outage tx but a different target: never paired with G.
        {"event": "Refueled", "target": C, "tx": "0xr9", "block": 12, "ts": 1003, "ref_tx": "0xd1", "fee_wei": 1},
        # WentDark is not a reaction outcome.
        {"event": "WentDark", "target": G, "tx": "0xr1", "block": 11, "ts": 1002, "ref_tx": "0xd1"},
    ]
    return series.build_rows("lasna", {G: "guarded", C: "control"}, darks, lits, reactions, [])


class PairingTest(unittest.TestCase):
    def test_reaction_is_paired_by_ref_tx_and_target_only(self):
        rows = lasna_rows()
        self.assertEqual([r["dark_tx"] for r in rows], ["0xd1", "0xd2", "0xd3"])
        first, control, second = rows
        self.assertEqual((first["reaction_tx"], first["outcome"], first["latency_s"]), ("0xr1", "Refueled", 2))
        self.assertNotIn("reaction_tx", control)
        self.assertEqual((second["outcome"], second["reason"]), ("GaveUp", "daily cap reached"))
        self.assertNotIn("lit_tx", second)

    def test_lit_must_fall_between_this_outage_and_the_next(self):
        darks = [dark(G, 10, 1000, "0xd1"), dark(G, 20, 2000, "0xd2")]
        rows = series.build_rows("lasna", {G: "guarded"}, darks, [lit(G, 21, 2005, "0xl2")], [], [])
        self.assertNotIn("lit_tx", rows[0])
        self.assertEqual(rows[1]["lit_tx"], "0xl2")

    def test_destination_callback_is_paired_by_seq(self):
        darks = [dark(G, 100, 5000, "0xb1")]
        reactions = [{"event": "RefuelRequested", "target": G, "tx": "0xr", "block": 7, "ts": 5002, "ref_tx": "0xb1",
                      "fee_wei": 3, "seq": 5}]
        callbacks = [{"event": "Refueled", "seq": 4, "target": G, "tx": "0xwrong", "ts": 5003, "fee_wei": 1},
                     {"event": "Refueled", "seq": 5, "target": G, "tx": "0xcb", "ts": 5004, "fee_wei": 2}]
        row = series.build_rows("base-sepolia", {G: "guarded"}, darks, [lit(G, 140, 5008, "0xl")], reactions, callbacks)[0]
        self.assertEqual((row["callback_tx"], row["callback_fee_wei"], row["latency_s"]), ("0xcb", 2, 8))

    def test_summary_and_control_status(self):
        rows = lasna_rows()
        s = series.summarize(rows)
        self.assertEqual((s["outages"], s["relit"], s["relit_pct"], s["median_s"]), (2, 1, 50.0, 2))
        self.assertEqual(s["reaction_fee_wei"], [7, 9])
        ctl = series.control_status(rows, {C: 123}, 1001 + 25 * 3600)[0]
        self.assertEqual((ctl["dark"], ctl["hours_dark"], ctl["debt_wei"]), (True, 25.0, 123))
        # G's last outage ended in GaveUp and was never relit: it counts as dark from that outage.
        last = series.control_status(rows, {G: 0}, 2000 + 3600)[0]
        self.assertEqual((last["dark"], last["dark_since_ts"], last["hours_dark"]), (True, 2000, 1.0))
        relit = series.control_status(rows[:2], {G: 0}, 3000)[0]
        self.assertFalse(relit["dark"])


class ReportTest(unittest.TestCase):
    def write_evidence(self, d, outages):
        rows = []
        for i in range(outages):
            rows.append({"side": "lasna", "role": "guarded", "target": G, "dark_tx": f"0x{i:064x}", "dark_block": i,
                         "dark_ts": 100 * i, "reaction_tx": f"0x{i + 1000:064x}", "reaction_ts": 100 * i + 1,
                         "reaction_fee_wei": 10**15, "outcome": "Refueled", "lit_tx": f"0x{i + 2000:064x}",
                         "lit_ts": 100 * i + 3, "latency_s": 3})
        rows.append({"side": "lasna", "role": "control", "target": C, "dark_tx": "0x" + "f" * 64, "dark_block": 1,
                     "dark_ts": 0})
        data = {"side": "lasna", "block_ranges": {"lasna": [1, 99]}, "as_of_ts": 30 * 3600, "rows": rows,
                "summary": {"guarded": series.summarize(rows, "guarded"), "control": series.summarize(rows, "control")},
                "controls": series.control_status(rows, {C: 5 * 10**16}, 30 * 3600)}
        (Path(d) / "E-005-series-lasna.json").write_text(json.dumps(data))

    def render(self, outages):
        cfg = series.pelitarpc.load_config("pelita.json")
        with tempfile.TemporaryDirectory() as d:
            self.write_evidence(d, outages)
            return report.render(Path(d), cfg, CHAINS), cfg

    def test_numbers_come_from_evidence_and_missing_parts_are_tbd(self):
        text, cfg = self.render(cfg_need := series.pelitarpc.load_config("pelita.json")["series"]["lasna_outages"])
        self.assertIn(f"| Guarded outages | at least {cfg_need} | {cfg_need} |", text)
        self.assertIn("| Median outage to relit (block timestamps) | at most 5 s | 3 s |", text)
        self.assertIn("| Result | | met |", text)
        self.assertIn(CHAINS["chains"]["lasna"]["explorer_tx"] + "0x" + "0" * 64, text)
        self.assertIn("<<TBD H2", text)  # no Base Sepolia evidence in the fixture
        self.assertNotIn("<<TBD H1", text)
        self.assertIn("| lasna | `" + C + "` | True | 30.0 | 0.05 | met |", text)

    def test_missed_target_is_reported_as_not_met(self):
        text, _ = self.render(3)
        self.assertIn("| Result | | **not met** |", text)

    def test_zero_reaction_fee_is_an_open_slot_not_free(self):
        # Reactive receipts on Lasna carry no fee (measured 25 Nov 2026); a median of 0 must not read as "free".
        with tempfile.TemporaryDirectory() as d:
            self.write_evidence(d, 3)
            p = Path(d) / "E-005-series-lasna.json"
            data = json.loads(p.read_text())
            data["summary"]["guarded"]["reaction_fee_wei"] = [0, 0, 0]
            p.write_text(json.dumps(data))
            text = report.render(Path(d), series.pelitarpc.load_config("pelita.json"), CHAINS)
        self.assertIn("| lasna | <<TBD H5", text)
        self.assertNotIn("| lasna | 0 |", text)

    def test_keeper_bill_is_read_from_its_balance(self):
        with tempfile.TemporaryDirectory() as d:
            self.write_evidence(d, 3)
            p = Path(d) / "E-005-series-lasna.json"
            data = json.loads(p.read_text())
            data["summary"]["guarded"]["reaction_billed_wei"] = [3 * 10**16, 10**16, 2 * 10**16]
            p.write_text(json.dumps(data))
            text = report.render(Path(d), series.pelitarpc.load_config("pelita.json"), CHAINS)
        self.assertIn("| lasna | 0.02 | n/a | 3 |", text)
        self.assertNotIn("<<TBD H5", text)

    def test_site_figures_match_the_measured_table_and_never_show_zero_as_free(self):
        with tempfile.TemporaryDirectory() as d:
            self.write_evidence(d, 3)
            p = Path(d) / "E-005-series-lasna.json"
            data = json.loads(p.read_text())
            data["summary"]["guarded"]["reaction_billed_wei"] = [3 * 10**16, 0, 10**16, 2 * 10**16]
            p.write_text(json.dumps(data))
            figs = report.site_figures(Path(d))
            text = report.render(Path(d), series.pelitarpc.load_config("pelita.json"), CHAINS)
            lasna = figs["relight"]["lasna"]
            self.assertEqual((lasna["reaction"], lasna["reaction_wei"], lasna["samples"]), ("0.02", str(2 * 10**16), 3))
            self.assertIn(f"| lasna | {lasna['reaction']} |", text)
            self.assertNotIn("base-sepolia", figs["relight"])
            data["summary"]["guarded"]["reaction_billed_wei"] = [0, 0]
            p.write_text(json.dumps(data))
            self.assertIsNone(report.site_figures(Path(d))["relight"]["lasna"]["reaction_wei"])

    def test_committed_page_figures_are_current(self):
        ev = Path(report.pelitarpc.ROOT) / "docs" / "evidence"
        committed = json.loads((Path(report.pelitarpc.ROOT) / "web" / "measured.json").read_text())
        self.assertEqual(committed, report.site_figures(ev))

    def test_base_control_that_never_went_dark_names_the_lost_beats(self):
        with tempfile.TemporaryDirectory() as d:
            self.write_evidence(d, 3)
            base = {"side": "base-sepolia", "rows": [], "as_of_ts": 1, "block_ranges": {"base-sepolia": [1, 2]}, "summary": {"guarded": series.summarize([])},
                    "controls": series.control_status([], {C: 0}, 1), "demo": {"beats": 450, "lit_guarded": 450,
                                                                               "lit_control": 4}}
            (Path(d) / "E-005-series-base-sepolia.json").write_text(json.dumps(base))
            text = report.render(Path(d), series.pelitarpc.load_config("pelita.json"), CHAINS)
        self.assertIn("| base-sepolia | `" + C + "` | False | 0 | 0 | no outage: it received 4 of 450 beats", text)

    def test_render_is_deterministic(self):
        self.assertEqual(self.render(3)[0], self.render(3)[0])


class CensusSectionTest(unittest.TestCase):
    @staticmethod
    def census(ts, outages, still_dark, same=True):
        chain = {"as_of_ts": ts, "outages": outages, "contracts": outages - 1, "still_dark": still_dark}
        return {"since_utc": "2026-11-04T04:18:00Z", "chains": {"lasna": chain}, "h8_equal": {"lasna": same},
                "repeat": {"lasna": f"census --to-block {ts}"}}

    def test_every_census_is_kept_newest_first(self):
        old, new = self.census(1794870011, 154, 97), self.census(1795770482, 570, 277, same=False)
        lines = report.census_section([old, None, new])
        rows = [ln for ln in lines if ln.startswith("| 2026-")]
        self.assertEqual(rows[0], "| 2026-11-27 09:08 | lasna | 570 | 569 | 277 | **no** | `census --to-block 1795770482` |")
        self.assertEqual(rows[1], "| 2026-11-16 23:00 | lasna | 154 | 153 | 97 | yes | `census --to-block 1794870011` |")

    def test_no_census_is_an_open_slot(self):
        self.assertIn("<<TBD H8", "\n".join(report.census_section([None, None])))


class BillTest(unittest.TestCase):
    K = "0x" + "b" * 40
    ARG = "0xcebbda8d" + "0" * 24 + "b" * 40

    def block(self, before, after, *txs):
        return {"before": before, "after": after, "txs": list(txs)}

    def test_bill_is_balance_drop_less_value_sent_split_over_reactions(self):
        r1, r2 = {"hash": "0x1", "to": "0x" + "8" * 40, "input": self.ARG}, {"hash": "0x2", "to": None, "input": self.ARG}
        other = {"hash": "0x3", "to": "0x" + "9" * 40, "input": "0x"}
        blocks = {5: self.block(1000, 700, r1, other), 6: self.block(700, 600, r1 | {"hash": "0x4"}, r2)}
        events = [{"tx": "0x1", "block": 5, "sent_wei": 250}, {"tx": "0x1", "block": 5}]
        self.assertEqual(series.billed_per_tx(blocks, self.K.upper().replace("0X", "0x"), events),
                         {"0x1": 50, "0x4": 50, "0x2": 50})

    def test_block_with_a_direct_call_or_no_positive_bill_gives_no_figure(self):
        react = {"hash": "0x1", "to": "0x" + "8" * 40, "input": self.ARG}
        topup = {"hash": "0x2", "to": self.K, "input": "0x"}
        blocks = {5: self.block(1000, 700, react, topup), 6: self.block(700, 700, react | {"hash": "0x5"})}
        self.assertEqual(series.billed_per_tx(blocks, self.K, []), {})


if __name__ == "__main__":
    unittest.main()
