"""Writes docs/measured.md from docs/evidence/*.json only (files produced by chain reads: census.py, series.py).

No number comes from this script's clock or from memory. A measurement that has no evidence file yet is written as a
`<<TBD ...>>` slot that names the command producing it, so the submission gate can see it is missing. Failed targets
are reported as failed.
"""

import argparse
import json
import statistics
import sys
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
        lines.append(f"| {side} | `{c['address']}` | {c['dark']} | {c['hours_dark']} | {coin(c['debt_wei'])} | {verdict(ok)} |")
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
    lines += ["Fees from transaction receipts (gas used times effective gas price).", "",
              "| Side | Keeper reaction (median, `lREACT`) | Callback (median, ETH) | Samples |", "|---|---|---|---|"]
    for side, s in fees.items():
        med = lambda xs: statistics.median(xs) if xs else None  # noqa: E731
        # A reactive transaction's receipt shows no fee (E-005, 25 Nov 2026): Lasna bills the reaction to the Keeper.
        # A median of zero would read as "free", so the slot stays open until that bill is read from the chain.
        react = (coin(med(s["reaction_fee_wei"])) if any(s["reaction_fee_wei"])
                 else "<<TBD H5: reaction receipts carry no fee; read what Lasna billed the Keeper>>")
        lines.append(f"| {side} | {react} | "
                     f"{coin(med(s['callback_fee_wei'])) if s['callback_fee_wei'] else 'n/a'} | {len(s['reaction_fee_wei'])} |")
    return lines + [""]


def census_section(census):
    lines = ["## H8. Census of dark contracts (no key)", ""]
    if not census:
        return lines + [tbd("H8", "python3 scripts/census.py"), ""]
    lines += [f"Since {census['since_utc']}. Same numbers as the page snapshot for the same block range: "
              f"{'yes' if all(census['h8_equal'].values()) else '**no**'}.", "", "| Chain | Outages | Contracts | Still dark | Repeat |",
              "|---|---|---|---|---|"]
    for name, c in census["chains"].items():
        t = c.get("totals", c)
        lines.append(f"| {name} | {t.get('outages', '?')} | {t.get('contracts', '?')} | {t.get('still_dark', '?')} | "
                     f"`{census['repeat'][name]}` |")
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
    lines += census_section(load(evidence, "E-003-census.json"))
    return "\n".join(lines).rstrip() + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Write docs/measured.md from docs/evidence/*.json.")
    ap.add_argument("--evidence", default=str(pelitarpc.ROOT / "docs" / "evidence"))
    ap.add_argument("--out", default=str(pelitarpc.ROOT / "docs" / "measured.md"))
    a = ap.parse_args(argv)
    text = render(Path(a.evidence), pelitarpc.load_config("pelita.json"), pelitarpc.load_config("chains.json"))
    Path(a.out).write_text(text, encoding="utf-8")
    print(f"report: {a.out} ({text.count('<<TBD')} TBD slots)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
