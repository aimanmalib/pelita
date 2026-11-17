#!/usr/bin/env python3
"""Render the link-preview card brand/og-card.png (1200x630) with headless Chromium.

Words come from web/lang/en.json (hero.*) and the domain from deploy/site.env; colours from the :root tokens of
web/css/site.css; the glyph from brand/logo.svg. Change those files, then run this again: nothing here holds copy.
Host tool (needs Playwright with Chromium installed). Not part of the offline gate;
tests/test_web.py checks the committed PNG (size, dimensions, meta tags).
"""
import html
import json
import pathlib
import re
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "brand" / "og-card.png"
WIDTH, HEIGHT = 1200, 630
MAX_BYTES = 300_000  # previews in WhatsApp/Facebook drop larger cards (PRD 4.7)
ROW = "lit lit lit lit dark lit lit lit lit lit lit".split()  # a fleet row with one lamp gone dark


def tokens():
    css = (ROOT / "web" / "css" / "site.css").read_text(encoding="utf-8")
    root = re.search(r":root\s*{(.*?)}", css, re.S)[1]
    return dict(re.findall(r"--([\w-]+):\s*([^;]+);", root))


def domain():
    env = (ROOT / "deploy" / "site.env").read_text(encoding="utf-8")
    return re.search(r"^DOMAIN=(\S+)$", env, re.M)[1]


def glyph_paths():
    svg = (ROOT / "brand" / "logo.svg").read_text(encoding="utf-8")
    return re.search(r"<g transform[^>]*>(.*?)</g>", svg, re.S)[1]


def card_html():
    t, en = tokens(), json.loads((ROOT / "web" / "lang" / "en.json").read_text(encoding="utf-8"))
    fonts = (ROOT / "web" / "fonts").as_uri()
    lamp = glyph_paths()
    row = "".join(
        f'<svg class="mini {s}" viewBox="0 0 24 24">{lamp}</svg>' for s in ROW
    )
    e = html.escape
    return f"""<!doctype html><meta charset="utf-8"><style>
@font-face {{ font-family: Newsreader; src: url("{fonts}/newsreader.woff2"); font-weight: 200 800; }}
@font-face {{ font-family: "Public Sans"; src: url("{fonts}/public-sans.woff2"); font-weight: 100 900; }}
@font-face {{ font-family: "Plex Mono"; src: url("{fonts}/ibm-plex-mono-400.woff2"); }}
html, body {{ margin: 0; width: {WIDTH}px; height: {HEIGHT}px; overflow: hidden; }}
body {{ background: radial-gradient(circle at 80% 38%, {t['amber-glow']}, transparent 46%), {t['bg']};
  color: {t['text']}; font-family: "Public Sans", sans-serif; position: relative; }}
.frame {{ position: absolute; inset: 28px; border: 1px solid {t['line-soft']}; border-radius: 22px; }}
.text {{ position: absolute; left: 84px; top: 78px; width: 640px; }}
.brand {{ display: flex; align-items: center; gap: 14px; font-family: Newsreader, serif; font-size: 40px; font-weight: 600; }}
.brand svg {{ width: 44px; height: 44px; }}
h1 {{ font-family: Newsreader, serif; font-weight: 500; font-size: 78px; line-height: 1.02; letter-spacing: -0.015em; margin: 54px 0 22px; }}
p {{ font-size: 28px; line-height: 1.35; color: {t['muted']}; margin: 0; max-width: 560px; }}
.big {{ position: absolute; right: 70px; top: 96px; width: 330px; height: 330px; }}
.row {{ position: absolute; left: 84px; bottom: 112px; display: flex; gap: 16px; }}
.mini {{ width: 30px; height: 30px; }}
.foot {{ position: absolute; left: 84px; right: 84px; bottom: 62px; display: flex; justify-content: space-between;
  font-family: "Plex Mono", monospace; font-size: 20px; color: {t['faint']}; }}
.foot b {{ font-weight: 400; color: {t['amber']}; }}
.dark path {{ fill: {t['ash-soft']}; }}
</style>
<div class="frame"></div>
<svg class="big" viewBox="0 0 24 24">{lamp}</svg>
<div class="text">
  <div class="brand"><svg viewBox="0 0 24 24">{lamp}</svg>Pelita</div>
  <h1>{e(en['hero.title'])}</h1>
  <p>{e(en['hero.lede'])}</p>
</div>
<div class="row">{row}</div>
<div class="foot"><span>{e(en['hero.tag'])}</span><b>{e(domain())}</b></div>
"""


def main():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1)
        with tempfile.TemporaryDirectory() as tmp:  # a file:// page, so the local fonts load
            src = pathlib.Path(tmp) / "card.html"
            src.write_text(card_html(), encoding="utf-8")
            page.goto(src.as_uri())
        page.evaluate("document.fonts.ready")
        page.screenshot(path=str(OUT), type="png")
        browser.close()
    size = OUT.stat().st_size
    print(OUT.relative_to(ROOT), size, "bytes")
    return 0 if size < MAX_BYTES else 1


if __name__ == "__main__":
    sys.exit(main())
