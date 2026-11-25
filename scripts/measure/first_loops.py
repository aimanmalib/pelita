"""First full loops (PRD 0.3, P2c): writes docs/evidence/E-004-first-loops.json from evidence already read off the chains.

Nothing is typed by hand and nothing is re-paired here. The inputs are the files the chain readers wrote:
  docs/evidence/E-005-series-lasna.json         series.py record --side lasna
  docs/evidence/E-005-series-base-sepolia.json  series.py record --side base-sepolia
  docs/evidence/E-004-demo-loop.json            spike/demo_loop_evidence.py
series.py pairs an outage and a reaction only when the reactive transaction's `refTx` IS the outage transaction, and a
Tank callback with its request only by sequence number; this script takes, for each path, the earliest guarded outage
whose loop closed (reaction, then, on a destination, the Tank's `Refueled`, then the ward whitelisted again) and lays
the steps out one hash each. A path with no closed loop is written as `closed: false` with the reason, never skipped.

Usage: python3 scripts/measure/first_loops.py [--out docs/evidence/E-004-first-loops.json]
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
EVIDENCE = ROOT / "docs" / "evidence"


def closed(row, destination):
    """A guarded outage whose loop finished: reacted, (on a destination) refuelled by the Tank, and whitelisted again."""
    if row.get("role") != "guarded" or "lit_tx" not in row or "reaction_tx" not in row:
        return False
    if destination:
        return row.get("outcome") == "RefuelRequested" and row.get("callback_event") == "Refueled"
    return row.get("outcome") == "Refueled"


def path_loop(series, destination):
    rows = series.get("rows", [])
    row = next((r for r in rows if closed(r, destination)), None)
    if row is None:
        guarded = [r for r in rows if r.get("role") == "guarded"]
        why = "no guarded outage yet" if not guarded else (
            f"{len(guarded)} guarded outage(s), none closed; last outcome: {guarded[-1].get('outcome', 'no reaction')}")
        return {"side": series.get("side"), "closed": False, "reason": why}
    steps = [{"step": "dark", "event": "BlacklistContract", "tx": row["dark_tx"], "block": row["dark_block"],
              "ts": row["dark_ts"]},
             {"step": "reaction", "event": row["outcome"], "tx": row["reaction_tx"], "block": row["reaction_block"],
              "ts": row["reaction_ts"], "refTx": row["dark_tx"], "fee_wei": row.get("reaction_fee_wei", 0)}]
    if destination:
        steps.append({"step": "callback", "event": row["callback_event"], "tx": row["callback_tx"],
                      "ts": row["callback_ts"], "fee_wei": row.get("callback_fee_wei", 0)})
    steps.append({"step": "relit", "event": "WhitelistContract", "tx": row["lit_tx"], "ts": row["lit_ts"]})
    return {"side": series["side"], "closed": True, "target": row["target"], "latency_s": row["latency_s"],
            "steps": steps}


def demo_loop(demo):
    v = demo.get("verdict", {})
    lit = next((d for d in demo.get("deliveries", []) if d.get("status") == 1), None)
    out = {"side": "demo", "closed": bool(v.get("lit")), "beat_number": demo.get("beat_number"),
           "steps": [{"step": "beat", "event": "Beat", "tx": demo["beat"]["tx"], "block": demo["beat"]["block"],
                      "ts": demo["beat"]["block_time"]}]}
    fr = demo.get("flicker_reaction")
    if fr:
        out["steps"].append({"step": "reaction", "event": "Forwarded", "tx": fr["tx"], "block": fr["block"],
                             "ts": fr["block_time"], "refTx": fr.get("refTx")})
    if lit:
        out["steps"].append({"step": "lit", "event": "Lit", "tx": lit["tx"], "block": lit["block"],
                             "ts": lit["block_time"]})
    return out


def build(lasna, base, demo):
    loops = [path_loop(lasna, False), path_loop(base, True), demo_loop(demo)]
    return {"_about": "First full loop of each path (PRD 0.3, P2c), taken by scripts/measure/first_loops.py from the "
                      "E-005 series files and E-004-demo-loop.json, which were read off the chains.",
            "sources": ["E-005-series-lasna.json", "E-005-series-base-sepolia.json", "E-004-demo-loop.json"],
            "loops": loops, "all_closed": all(lp["closed"] for lp in loops)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--evidence", default=str(EVIDENCE))
    ap.add_argument("--out", default=str(EVIDENCE / "E-004-first-loops.json"))
    a = ap.parse_args(argv)
    d = Path(a.evidence)
    load = lambda n: json.loads((d / n).read_text(encoding="utf-8"))  # noqa: E731
    out = build(load("E-005-series-lasna.json"), load("E-005-series-base-sepolia.json"), load("E-004-demo-loop.json"))
    Path(a.out).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    for lp in out["loops"]:
        print(f"{lp['side']}: {'closed' if lp['closed'] else 'OPEN - ' + lp['reason']}")
    return 0 if out["all_closed"] else 1


if __name__ == "__main__":
    sys.exit(main())
