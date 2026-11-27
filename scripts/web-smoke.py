#!/usr/bin/env python3
"""Browser smoke test of web/ on Chromium 1440 px and WebKit iPhone 13 (+ 320 px), each in light and dark.

Serves the site the way deploy/ will: web/ at /, config/chains.json at /config/, brand/ at /brand/, and a snapshot at
/data/snapshot.json (default: tests/fixtures/snapshot-sample.json with its times shifted to now). The Lasna RPC is
answered by a stub so the fuel gauge is tested without the network. Checks: no console errors, no failed requests,
no horizontal overflow, gauge validates and reads, language toggle swaps every text (the gauge reading too),
dark table shows debt, cost block and gauge estimate match web/measured.json, no overflow with every FAQ answer open
or with the phone menu open after scrolling, touch targets of at least 44 px, the theme switch, the forced proof
states (?keadaan=muat|kosong|ralat), and a 10 s wait without a crash. Screenshots go to
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


SITE = json.loads((ROOT / "web" / "site.json").read_text(encoding="utf-8"))


def note_missing(page, lang, problems):
    """The gauge estimate note must be on the page, in this language, carrying the measured fee."""
    fee = json.loads((ROOT / "web" / "measured.json").read_text())["relight"][SITE["gauge_fee_side"]]["reaction"]
    before, after = LANG[lang]["gauge.leftNote"].split("{fee}")
    notes = page.eval_on_selector_all("#gauge-out p.note", "els => els.map(e => e.textContent.trim())")
    if not any(n.startswith(before) and n.endswith(after) and f"{before}{fee} " in n for n in notes):
        problems.append(f"gauge estimate note ({lang}) with fee {fee} is not shown: {notes}")


# Controls that must be easy to tap. Inline links inside running text are exempt (WCAG 2.5.8 inline exception).
TARGETS = ".top a, .top button, .top summary, .mnav-panel a, .cta a, .btn, .faq-list summary, .foot-links a, #theme"


def small_targets(page):
    return page.evaluate("""s => [...document.querySelectorAll(s)].filter(e => {
        const r = e.getBoundingClientRect();
        if (e.closest('details:not([open])') && !e.matches('summary')) return false;  // folded away, not tappable
        return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== 'hidden' && (r.width < 43.5 || r.height < 43.5);
      }).map(e => `${e.id || e.className || e.tagName} ${Math.round(e.getBoundingClientRect().width)}x${Math.round(e.getBoundingClientRect().height)}`)""", TARGETS)


def chrome(page, label, shots, problems):
    """FAQ, phone menu (opened after scrolling), touch targets, theme switch: none may overflow the page."""
    small = small_targets(page)
    if small:
        problems.append(f"touch targets under 44 px: {small}")
    answers = page.eval_on_selector_all(".faq-list details", "els => els.length")
    if answers < 6:
        problems.append(f"FAQ has {answers} questions, want at least 6")
    for summary in page.query_selector_all(".faq-list summary"):
        summary.click()
    empty = page.eval_on_selector_all(".faq-list details[open] p", "els => els.filter(e => !e.textContent.trim()).length")
    if empty or page.eval_on_selector_all(".faq-list details[open]", "els => els.length") != answers:
        problems.append("FAQ answers do not open or are empty")
    overflow(page, "with the FAQ open", problems)
    page.locator("#faq").scroll_into_view_if_needed()
    page.screenshot(path=str(shots / f"{label}-faq.png"))
    demo = page.get_attribute("#demo-link", "href") or ""
    if not demo.startswith("http"):
        problems.append(f"demo button has no target: {demo!r}")
    if page.is_visible("#mnav summary"):
        page.evaluate("window.scrollTo({top: 1600, behavior: 'instant'})")
        page.wait_for_timeout(150)
        page.click("#mnav summary")
        page.wait_for_timeout(150)
        box = page.evaluate("() => { const r = document.querySelector('.mnav-panel').getBoundingClientRect(); return [r.left, r.right, innerWidth]; }")
        if not page.is_visible(".mnav-panel a") or box[0] < 0 or box[1] > box[2]:
            problems.append(f"phone menu panel not shown inside the viewport {box}")
        overflow(page, "with the phone menu open", problems)
        page.screenshot(path=str(shots / f"{label}-menu.png"))
        page.click(".mnav-panel a[href='#faq']")
        page.wait_for_timeout(300)
        if page.evaluate("document.getElementById('mnav').open"):
            problems.append("phone menu stays open after a jump")
    before = page.evaluate("getComputedStyle(document.body).backgroundColor")
    page.click("#theme")
    page.wait_for_timeout(200)
    if page.evaluate("getComputedStyle(document.body).backgroundColor") == before:
        problems.append("theme switch does not change the page")
    overflow(page, "after the theme switch", problems)
    page.click("#theme")
    if label.startswith("webkit"):
        page.wait_for_timeout(10000)  # animated blur crashed WebKit seconds after load on other pages; stay a while
        if page.evaluate("1 + 1") != 2:
            problems.append("page died during the 10 s wait")


def states(page, url, label, shots, problems):
    """Each forced state of the live proof row draws its own line, never a raw key."""
    for state in ("muat", "kosong", "ralat"):
        page.goto(f"{url}{'&' if '?' in url else '?'}keadaan={state}", wait_until="networkidle")
        page.wait_for_function("s => document.getElementById('proof').dataset.status === s", arg=state, timeout=8000)
        line = (page.text_content("#fresh") or "").strip()
        if not line or line in LANG["en"] and "." in line and " " not in line:
            problems.append(f"proof state {state} shows {line!r}")
        overflow(page, f"in state {state}", problems)
        page.locator("#proof").screenshot(path=str(shots / f"{label}-state-{state}.png"))


def check(page, url, label, shots, errors):
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
    note_missing(page, "en", problems)
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
    note_missing(page, "ms", problems)
    if LANG["ms"]["dark.colDebt"] != page.text_content("#darktable th:last-child").strip():
        problems.append("dark table debt column not translated")
    overflow(page, "in BM", problems)
    page.screenshot(path=str(shots / f"{label}-ms.png"), full_page=True)
    page.click("#lang")
    page.wait_for_function("h => document.querySelector('h1').textContent === h", arg=en_h1, timeout=5000)
    page.evaluate("window.scrollTo({top: 0, behavior: 'instant'})")
    page.wait_for_timeout(200)
    page.screenshot(path=str(shots / f"{label}-top.png"))
    chrome(page, label, shots, problems)
    states(page, url, label, shots, problems)
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
        sizes = [
            ("chromium-1440", p.chromium, {"viewport": {"width": 1440, "height": 900}}),
            ("webkit-iphone13", p.webkit, dict(iphone)),
            ("webkit-320", p.webkit, {**iphone, "viewport": {"width": 320, "height": 640}}),
        ]
        profiles = [(f"{name}-{scheme}", engine, {**opts, "color_scheme": scheme})
                    for name, engine, opts in sizes for scheme in ("light", "dark")]
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
            ok = check(page, url, label, shots, errors) and ok
            browser.close()
    if server:
        server.shutdown()
    print(f"screenshots: {shots}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
