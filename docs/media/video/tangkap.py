"""Capture the REAL page and explorers for the demo video -> work/aset/*.png + kotak.json.

Desktop = Chromium at 2x pixels. Only GET/HEAD, plus read-only JSON-RPC POSTs to the configured RPC hosts (eth_call for the
gauge). Nothing is signed or sent. Run: python3 docs/media/video/tangkap.py
"""
import json
import shutil
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[3]
ASET = Path(__file__).parent / "work" / "aset"
ASET.mkdir(parents=True, exist_ok=True)
CFG = json.loads((Path(__file__).parent / "garis.json").read_text())["tangkap"]
CHAINS = json.loads((ROOT / "config" / "chains.json").read_text())
RPC = tuple(c["rpc"] for c in CHAINS["chains"].values() if c.get("rpc"))
kotak = {}
for font in (ROOT / "web" / "fonts").glob("*.woff2"):  # the stage uses the page's own fonts
    shutil.copy(font, ASET / font.name)


def rel(pg, sel):
    b = pg.locator(sel).first.bounding_box()
    return {"x": b["x"], "y": b["y"], "w": b["width"], "h": b["height"]}


def guard(ctx):
    def route(r):
        ok = r.request.method in ("GET", "HEAD") or (r.request.method == "POST" and r.request.url.startswith(RPC))
        r.continue_() if ok else r.abort()
    ctx.route("**/*", route)


def section(pg, sel, name, pad=0):
    pg.locator(sel).first.scroll_into_view_if_needed()
    pg.wait_for_timeout(600)
    pg.locator(sel).first.screenshot(path=ASET / f"{name}.png")
    print("ok", name)


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1280, "height": 800}, device_scale_factor=2, color_scheme="dark", locale="en-US")
    guard(ctx)
    pg = ctx.new_page()
    pg.goto(CFG["laman"], wait_until="networkidle")
    pg.wait_for_timeout(2500)
    pg.screenshot(path=ASET / "d-hero.png")
    # a sticky header would be painted into element screenshots further down the page
    pg.evaluate("""() => { for (const e of document.querySelectorAll('body *')) {
      const p = getComputedStyle(e).position; if (p === 'sticky' || p === 'fixed') e.style.position = 'static'; } }""")
    for sel, name in (("#fleet", "d-fleet"), ("#try", "d-try"), ("#dark", "d-dark"), ("#how", "d-how")):
        section(pg, sel, name)
    pg.fill("#gauge-addr", CFG["gauge_alamat"])
    pg.click("#gauge-btn")
    pg.wait_for_timeout(6000)
    section(pg, "#gauge", "d-gauge")
    ctx.close()

    for name, url in CFG["penjelajah"].items():
        ctx = b.new_context(viewport={"width": 1280, "height": 800}, device_scale_factor=2, color_scheme="dark", locale="en-US")
        guard(ctx)
        pg = ctx.new_page()
        try:
            pg.goto(url, wait_until="networkidle", timeout=60000)
        except Exception as e:  # explorers keep sockets open; a loaded page is enough
            print("networkidle timeout", name, type(e).__name__)
        pg.wait_for_timeout(4000)
        pg.screenshot(path=ASET / f"{name}.png")
        print("ok", name)
        ctx.close()
    b.close()

(ASET / "kotak.json").write_text(json.dumps(kotak, indent=1))
