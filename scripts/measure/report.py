"""Writes docs/measured.md (and web/measured.json, the H5 figures the page shows) from docs/evidence/*.json only (files produced by chain reads: census.py, series.py).

No number comes from this script's clock or from memory. A measurement that has no evidence file yet is written as a
`<<TBD ...>>` slot that names the command producing it, so the submission gate can see it is missing. Failed targets
are reported as failed.
"""

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lib"))
import pelitarpc  # noqa: E402

WEI = Decimal(10) ** 18


def coin(wei):
    if wei is None:
        return "n/a"
    q = (Decimal(wei) / WEI).normalize()
    return f"{q:f}"


def num(x):
    return int(x) if isinstance(x, float) and x.is_integer() else x


def load(evidence, name):
    p = evidence / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def tbd(what, cmd):
    return f"<<TBD {what}: run `{cmd}`>>"


def verdict(ok):
    return "met" if ok else "**not met**"


def outage_section(title, data, side, need, target_s, symbol, explorers):
    cmd = f"python3 scripts/measure/series.py record --side {side}"
    lines = [f"## {title}", ""]
    if not data:
        return lines + [tbd(title.split('.')[0], cmd), ""]
    s = data["summary"]["guarded"]
    ranges = ", ".join(f"{k} blocks {a}-{b}" for k, (a, b) in data["block_ranges"].items())
    ok = s["outages"] >= need and s["relit"] == s["outages"] and s["median_s"] is not None and s["median_s"] <= target_s
    lines += [
        f"Source: `docs/evidence/E-005-series-{side}.json` ({ranges}). Repeat: `{cmd}`.",
        "",
        "| Measure | Target | Measured |",
        "|---|---|---|",
        f"| Guarded outages | at least {need} | {s['outages']} |",
        f"| Relit | 100% | {s['relit']} ({s['relit_pct']}%) |",
        f"| Median outage to relit (block timestamps) | at most {target_s} s | {num(s['median_s'])} s |",
        f"| Slowest | | {num(s['max_s'])} s |",
        f"| Result | | {verdict(ok)} |",
        "",
        "| Outage tx | Keeper reaction tx | Outcome | Callback tx | Relit tx | Seconds |",
        "|---|---|---|---|---|---|",
    ]
    for r in data["rows"]:
        if r["role"] != "guarded":
            continue
        link = lambda tx, chain: f"[{tx[:10]}]({explorers[chain]}{tx})" if tx else "-"  # noqa: E731
        lines.append(
            f"| {link(r['dark_tx'], side)} | {link(r.get('reaction_tx'), 'lasna')} | {r.get('outcome', 'none')}"
            f"{' (' + r['reason'] + ')' if r.get('reason') else ''} | {link(r.get('callback_tx'), side)} | "
            f"{link(r.get('lit_tx'), side)} | {r.get('latency_s', '-')} |"
        )
    return lines + [""]


def control_section(series, hours):
    lines = ["## H3. Control pair without Pelita", ""]
    rows = [(side, c) for side, d in series.items() if d for c in d.get("controls", [])]
    if not rows:
        return lines + [tbd("H3", "python3 scripts/measure/series.py record --side <chain>"), ""]
    lines += [f"Target: stays dark for at least {hours} hours with `debt()` above 0.", "",
              "| Chain | Contract | Dark at last block | Hours dark | debt() | Result |", "|---|---|---|---|---|---|"]
    for side, c in rows:
        ok = c["dark"] and c["hours_dark"] >= hours and c["debt_wei"] > 0
        result = verdict(ok)
        demo = (series[side] or {}).get("demo") or {}
        never = not any(r["target"] == c["address"] for r in series[side]["rows"])
        if never and demo and demo.get("lit_control", 0) < demo.get("beats", 0):
            # The control Lantern only spends gas when a beat reaches it; with its upstream control dark, none do.
            result = (f"no outage: it received {demo['lit_control']} of {demo['beats']} beats, because its upstream "
                      "control on Lasna is dark (H4)")
        lines.append(f"| {side} | `{c['address']}` | {c['dark']} | {c['hours_dark']} | {coin(c['debt_wei'])} | {result} |")
    return lines + [""]


def beats_section(data, side):
    lines = ["## H4. Lost beats, guarded against control", ""]
    demo = (data or {}).get("demo")
    if not demo:
        return lines + [tbd("H4", f"python3 scripts/measure/series.py record --side {side}"), ""]
    lines += ["Same Beacon, same beats, same block range.", "", "| | Beats sent | Lights received | Lost |", "|---|---|---|---|"]
    for role in ("guarded", "control"):
        got = demo.get(f"lit_{role}", 0)
        lines.append(f"| {role.capitalize()} | {demo['beats']} | {got} | {demo['beats'] - got} |")
    return lines + [""]


def cost_section(series, chains):
    lines = ["## H5. Cost of one relight", ""]
    fees = {side: d["summary"]["guarded"] for side, d in series.items() if d}
    if not fees:
        return lines + [tbd("H5", "python3 scripts/measure/series.py record --side <chain>"), ""]
    lines += ["Callback: fee from its receipt (gas used times effective gas price). Keeper reaction: a reactive receipt shows",
              "no fee, so the figure is what Lasna took from the Keeper's balance in the reaction's block, less the `lREACT`",
              "it sent to the ward (`scripts/measure/series.py`, `billed_per_tx`). Blocks where anything else called the",
              "Keeper are left out.", "",
              "| Side | Keeper reaction billed (median, `lREACT`) | Callback (median, ETH) | Samples |", "|---|---|---|---|"]
    for side, s in fees.items():
        med = lambda xs: statistics.median(xs) if xs else None  # noqa: E731
        # A median of zero would read as "free", so a side with no positive bill keeps the slot open.
        billed = [x for x in s.get("reaction_billed_wei", []) if x > 0]
        react = coin(med(billed)) if billed else "<<TBD H5: no clean Keeper bill read on Lasna yet>>"
        lines.append(f"| {side} | {react} | "
                     f"{coin(med(s['callback_fee_wei'])) if s['callback_fee_wei'] else 'n/a'} | {len(billed)} |")
    return lines + [""]


def site_figures(evidence):
    """The H5 medians the page shows, in the same decimal form as docs/measured.md (web/measured.json)."""
    med = lambda xs: statistics.median(xs) if xs else None  # noqa: E731
    out = {"_about": "Generated by scripts/measure/report.py with docs/measured.md. Do not edit by hand.",
           "source": "docs/measured.md#h5-cost-of-one-relight", "relight": {}}
    for side in ("lasna", "base-sepolia"):
        data = load(evidence, f"E-005-series-{side}.json")
        if not data:
            continue
        s = data["summary"]["guarded"]
        billed = med([x for x in s.get("reaction_billed_wei", []) if x > 0])
        cb = med(s.get("callback_fee_wei") or [])
        out["relight"][side] = {
            "reaction": coin(billed) if billed is not None else None,
            "reaction_wei": str(int(billed)) if billed is not None else None,
            "callback": coin(cb) if cb is not None else None,
            "samples": len([x for x in s.get("reaction_billed_wei", []) if x > 0]),
        }
    return out


CENSUS_FILES = ("E-003-census.json", "E-006-census.json")  # oldest first; a later census repeats the earlier range


def census_end(census):
    return max(c.get("as_of_ts", 0) for c in census["chains"].values())


def census_section(censuses):
    """H8 rows for every census file, newest first. The older rows stay because the video and older text cite them."""
    lines = ["## H8. Census of dark contracts (no key)", ""]
    censuses = sorted((c for c in censuses if c), key=census_end, reverse=True)
    if not censuses:
        return lines + [tbd("H8", "python3 scripts/census.py"), ""]
    lines += [f"Since {censuses[0]['since_utc']}. Each census counts from that date to the last block of its range, so a "
              "newer census includes the older one. \"Same as page\" = the page snapshot gave the same numbers for the "
              "same block range.", "",
              "| Counted up to (UTC) | Chain | Outages | Contracts | Still dark | Same as page | Repeat |",
              "|---|---|---|---|---|---|---|"]
    for census in censuses:
        for name, c in census["chains"].items():
            t = c.get("totals", c)
            end = datetime.fromtimestamp(c["as_of_ts"], timezone.utc).strftime("%Y-%m-%d %H:%M") if "as_of_ts" in c else "?"
            same = "yes" if census["h8_equal"].get(name) else "**no**"
            lines.append(f"| {end} | {name} | {t.get('outages', '?')} | {t.get('contracts', '?')} | "
                         f"{t.get('still_dark', '?')} | {same} | `{census['repeat'][name]}` |")
    return lines + [""]


def render(evidence, cfg, chains):
    ser = cfg["series"]
    explorers = {n: c["explorer_tx"] for n, c in chains["chains"].items()}
    lasna = load(evidence, "E-005-series-lasna.json")
    base = load(evidence, "E-005-series-base-sepolia.json")
    lines = [
        "# Measured results",
        "",
        "Generated by `scripts/measure/report.py` from the evidence files in `docs/evidence/`, which are chain reads.",
        "Times are block timestamps. Testnet only: Reactive Lasna and Base Sepolia. Targets that were missed say so.",
        "",
    ]
    lines += outage_section("H1. Lasna outages relit by the Keeper", lasna, "lasna", ser["lasna_outages"],
                            ser["lasna_median_target_s"], "lREACT", explorers)
    lines += outage_section("H2. Base Sepolia outages relit through a callback", base, "base-sepolia",
                            ser["base_sepolia_outages"], ser["base_sepolia_median_target_s"], "ETH", explorers)
    lines += control_section({"lasna": lasna, "base-sepolia": base}, ser["control_dark_hours"])
    lines += beats_section(base, "base-sepolia")
    lines += cost_section({"lasna": lasna, "base-sepolia": base}, chains)
    lines += census_section([load(evidence, f) for f in CENSUS_FILES])
    return "\n".join(lines).rstrip() + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Write docs/measured.md from docs/evidence/*.json.")
    ap.add_argument("--evidence", default=str(pelitarpc.ROOT / "docs" / "evidence"))
    ap.add_argument("--out", default=str(pelitarpc.ROOT / "docs" / "measured.md"))
    ap.add_argument("--site-out", default=str(pelitarpc.ROOT / "web" / "measured.json"))
    a = ap.parse_args(argv)
    text = render(Path(a.evidence), pelitarpc.load_config("pelita.json"), pelitarpc.load_config("chains.json"))
    Path(a.out).write_text(text, encoding="utf-8")
    Path(a.site_out).write_text(json.dumps(site_figures(Path(a.evidence)), indent=2) + "\n", encoding="utf-8")
    print(f"report: {a.out} ({text.count('<<TBD')} TBD slots)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
