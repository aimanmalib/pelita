#!/usr/bin/env python3
"""Browser smoke test of web/ on Chromium (desktop + 390 px) and WebKit iPhone 13 (+ 320 px).

Serves the site the way deploy/ will: web/ at /, config/chains.json at /config/, brand/ at /brand/, and a snapshot at
/data/snapshot.json (default: tests/fixtures/snapshot-sample.json with its times shifted to now). The Lasna RPC is
answered by a stub so the fuel gauge is tested without the network. Checks: no console errors, no failed requests,
no horizontal overflow, gauge validates and reads, language toggle swaps every text (the gauge reading too),
dark table shows debt, cost block and gauge estimate match web/measured.json. Screenshots go to
$AUTOPILOT_BUKTI_DIR (or out/web-smoke/).

Host tool (Playwright), not part of the offline gate:
    python3 scripts/web-smoke.py [--snapshot FILE] [--url https://pelita.sasateguh.com/]
"""
import argparse
import functools
import http.server
import json
import os
import pathlib
import sys
import threading
import time

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "snapshot-sample.json"
WORD = "0x" + "0" * 46 + "{:018x}"


def shifted(path):
    snap = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    delta = int(time.time()) - snap.get("generated_at", 0)
    snap["generated_at"] += delta
    for e in snap.get("events", []):
        if "ts" in e:
            e["ts"] += delta
    if snap.get("demo", {}).get("last_beat_ts"):
        snap["demo"]["last_beat_ts"] += delta
    return json.dumps(snap).encode()


class Handler(http.server.SimpleHTTPRequestHandler):
    snapshot = b"{}"

    def translate_path(self, path):
        path = path.split("?", 1)[0]
        for prefix, base in (("/config/", ROOT / "config"), ("/brand/", ROOT / "brand")):
            if path.startswith(prefix):
                return str(base / path[len(prefix):])
        return str(ROOT / "web" / path.lstrip("/"))

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/data/snapshot.json":
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("cache-control", "no-store")
            self.end_headers()
            self.wfile.write(self.snapshot)
            return
        super().do_GET()

    def log_message(self, *args):
        pass


def rpc_stub(route):
    calls = json.loads(route.request.post_data or "[]")
    values = [4_200_000_000_000_000, 0, 1_000_000_000_000_000]  # debt, reserves, balance
    out = [{"jsonrpc": "2.0", "id": c["id"], "result": WORD.format(values[i % 3])} for i, c in enumerate(calls)]
    route.fulfill(status=200, content_type="application/json", headers={"access-control-allow-origin": "*"}, body=json.dumps(out))


LANG = {n: json.loads((ROOT / "web" / "lang" / f"{n}.json").read_text(encoding="utf-8")) for n in ("en", "ms")}
GAUGE_KEYS = [k for k in LANG["en"] if k.startswith("gauge.") or k in ("fleet.dark", "fleet.lit")]
# Texts every gauge reading draws, whatever the contract state (gauge.js render()).
GAUGE_READING_KEYS = ["gauge.debt", "gauge.reserves", "gauge.balance", "gauge.left", "gauge.fill", "gauge.own"]


def overflow(page, when, problems):
    over = page.evaluate("() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]")
    if over[0] > over[1]:
        problems.append(f"horizontal overflow {when} {over}")


def check(page, label, shots, errors):
    problems = []
    page.wait_for_selector("#cards .card, #cards .empty", timeout=15000)
    page.wait_for_timeout(400)
    overflow(page, "on load", problems)
    if not page.text_content("#darktable th:last-child").strip() == LANG["en"]["dark.colDebt"]:
        problems.append("dark table has no debt column")
    if "lREACT" not in (page.text_content("#darktable tbody") or ""):
        problems.append("dark table rows show no debt")
    # read the gauge FIRST, then switch language: the reading must be drawn again in the new language
    page.fill("#gauge-addr", "0x123")
    page.click("#gauge-btn")
    if "0x" not in (page.text_content("#gauge-msg") or ""):
        problems.append("gauge accepted a bad address")
    page.fill("#gauge-addr", "0x" + "ab" * 20)
    page.click("#gauge-btn")
    page.wait_for_selector("#gauge-out:not([hidden]) pre", timeout=8000)
    if "depositTo(address)" not in page.text_content("#gauge-out"):
        problems.append("gauge output lacks the depositTo command")
    overflow(page, "after gauge", problems)
    # H5 figures: the cost block and the gauge estimate come from web/measured.json, which report.py writes
    measured = json.loads((ROOT / "web" / "measured.json").read_text())["relight"]
    cost = page.eval_on_selector_all("#cost .amt .mono", "els => els.map(e => e.textContent.trim())")
    want = [v for f in measured.values() for v in (f["reaction"], f["callback"]) if v]
    if cost != want:
        problems.append(f"cost block shows {cost}, measured.json has {want}")
    if LANG["en"]["gauge.leftPending"] in page.text_content("#gauge-out"):
        problems.append("gauge still says the fee is pending although measured.json has it")
    page.screenshot(path=str(shots / f"{label}-en.png"), full_page=True)
    en_h1 = page.text_content("h1")
    page.click("#lang")
    page.wait_for_function("h => document.querySelector('h1').textContent !== h", arg=en_h1, timeout=5000)
    ms_h1 = page.text_content("h1")
    leftover = page.evaluate("""() => [...document.querySelectorAll('[data-i18n]')]
        .filter(e => /^[a-z]+\\.[A-Za-z0-9]+$/.test(e.textContent.trim())).map(e => e.dataset.i18n)""")
    if leftover:
        problems.append(f"untranslated keys {leftover}")
    # Per element, exact match: text_content() of the whole box glues nodes together, so a regex over it never fires.
    gauge_ms = page.eval_on_selector_all(
        "#gauge-out dt, #gauge-out dd, #gauge-out p, #gauge-out .pill", "els => els.map(e => e.textContent.trim())"
    )
    stale = [k for k in GAUGE_KEYS if LANG["en"][k] != LANG["ms"][k] and LANG["en"][k] in gauge_ms]
    if stale:
        problems.append(f"gauge reading still in English after switching: {stale}")
    missing = [k for k in GAUGE_READING_KEYS if LANG["ms"][k] not in gauge_ms]
    if missing:
        problems.append(f"gauge reading lacks BM text after switching: {missing}")
    if LANG["ms"]["dark.colDebt"] != page.text_content("#darktable th:last-child").strip():
        problems.append("dark table debt column not translated")
    overflow(page, "in BM", problems)
    page.screenshot(path=str(shots / f"{label}-ms.png"), full_page=True)
    page.click("#lang")
    page.wait_for_function("h => document.querySelector('h1').textContent === h", arg=en_h1, timeout=5000)
    page.evaluate("window.scrollTo({top: 0, behavior: 'instant'})")
    page.wait_for_timeout(200)
    page.screenshot(path=str(shots / f"{label}-top.png"))
    problems += errors
    print(f"{label}: {'OK' if not problems else 'FAIL'} h1 en={en_h1!r} ms={ms_h1!r}")
    for p in problems:
        print(f"  - {p}")
    return not problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default=str(FIXTURE))
    ap.add_argument("--url", help="test a deployed site instead of the local server")
    args = ap.parse_args()
    shots = pathlib.Path(os.environ.get("AUTOPILOT_BUKTI_DIR") or ROOT / "out" / "web-smoke")
    shots.mkdir(parents=True, exist_ok=True)
    server = None
    url = args.url
    if not url:
        Handler.snapshot = shifted(args.snapshot)
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{server.server_port}/"
    lasna_rpc = json.loads((ROOT / "config" / "chains.json").read_text())["chains"]["lasna"]["rpc"]
    ok = True
    with sync_playwright() as p:
        iphone = p.devices["iPhone 13"]
        profiles = [
            ("chromium-desktop", p.chromium, {"viewport": {"width": 1366, "height": 900}}),
            ("chromium-390", p.chromium, {"viewport": {"width": 390, "height": 844}, "device_scale_factor": 2}),
            ("webkit-iphone13", p.webkit, dict(iphone)),
            ("webkit-320", p.webkit, {**iphone, "viewport": {"width": 320, "height": 640}}),
        ]
        for label, engine, opts in profiles:
            browser = engine.launch()
            page = browser.new_context(**opts).new_page()
            errors = []
            page.on("console", lambda m, e=errors: m.type == "error" and e.append(f"console: {m.text}"))
            page.on("pageerror", lambda x, e=errors: e.append(f"pageerror: {x}"))
            page.on("requestfailed", lambda r, e=errors: e.append(f"requestfailed: {r.url}"))
            page.on("response", lambda r, e=errors: r.status >= 400 and e.append(f"HTTP {r.status}: {r.url}"))
            page.route(lasna_rpc.rstrip("/") + "*", rpc_stub)
            page.goto(url, wait_until="networkidle")
            ok = check(page, label, shots, errors) and ok
            browser.close()
    if server:
        server.shutdown()
    print(f"screenshots: {shots}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
