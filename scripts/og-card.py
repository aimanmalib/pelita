#!/usr/bin/env python3
"""Render the link-preview card brand/og-card.png (1200x630) with headless Chromium.

The card is the page's own hero, cut to a preview: brand mark, headline and testnet tag on the left; the real
product shots (web/site.json "shots") in the same CSS browser and phone frames on the right, the domain in the
browser bar. Words come from web/lang/en.json (hero.*), the domain from deploy/site.env, colours, type and frames
from web/css (token.css, site.css, frames.css), the lamp from brand/logo.svg. Change those files, then run this
again: nothing here holds copy or colour.
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


def domain():
    env = (ROOT / "deploy" / "site.env").read_text(encoding="utf-8")
    return re.search(r"^DOMAIN=(\S+)$", env, re.M)[1]


def glyph_paths():
    svg = (ROOT / "brand" / "logo.svg").read_text(encoding="utf-8")
    paths = re.findall(r"<path [^>]*d=\"([^\"]+)\"", re.search(r"<g transform[^>]*>(.*?)</g>", svg, re.S)[1])
    body, base, flame, core = paths
    return (f'<path class="b" d="{body}"/><path class="b" d="{base}"/>'
            f'<path class="f" d="{flame}"/><path class="c" d="{core}"/>')


def card_html():
    en = json.loads((ROOT / "web" / "lang" / "en.json").read_text(encoding="utf-8"))
    shots = json.loads((ROOT / "web" / "site.json").read_text(encoding="utf-8"))["shots"]
    web = ROOT / "web"
    css = "".join(f'<link rel="stylesheet" href="{(web / "css" / n).as_uri()}">'
                  for n in ("token.css", "site.css", "frames.css"))
    lamp = glyph_paths()
    e = html.escape
    return f"""<!doctype html><html data-tema="terang"><meta charset="utf-8">{css}<style>
html, body {{ width: {WIDTH}px; height: {HEIGHT}px; overflow: hidden; }}
.og {{ position: relative; width: {WIDTH}px; height: {HEIGHT}px; isolation: isolate; }}
.og .text {{ position: absolute; left: 72px; top: 64px; bottom: 72px; width: 470px; display: flex; flex-direction: column; }}
.og .brand {{ font-size: 34px; gap: 12px; min-height: 0; }}
.og .brand svg {{ width: 44px; height: 44px; }}
.og .b {{ fill: var(--teks); }} .og .f {{ fill: var(--aksen); }} .og .c {{ fill: var(--amber-core); }}
.og h1 {{ font-size: 76px; line-height: .98; letter-spacing: -0.04em; font-weight: 800; margin-top: 48px; max-width: 9ch; }}
.og .tag {{ font-size: 19px; margin-top: auto; align-self: flex-start; }}
.og .slab {{ inset: 56px -40px -40px 560px; }}
.og .browser {{ position: absolute; left: 640px; top: 96px; width: 640px; border-top-right-radius: 0; border-bottom-right-radius: 0; }}
.og .phone {{ position: absolute; left: 556px; top: 214px; width: 200px; padding: 6px; border-radius: 34px; }}
.og .phone img {{ border-radius: 28px; }}
</style>
<div class="og">
  <div class="slab" aria-hidden="true"></div>
  <figure class="browser"><div class="bar"><i></i><i></i><i></i><span>{e(domain())}</span></div>
    <img src="{(web / shots['desktop']['src']).as_uri()}" alt=""></figure>
  <figure class="phone"><img src="{(web / shots['phone']['src']).as_uri()}" alt=""></figure>
  <div class="text">
    <div class="brand"><svg viewBox="0 0 24 24">{lamp}</svg>Pelita</div>
    <h1>{e(en['hero.title'])}</h1>
    <p class="tag">{e(en['hero.tag'])}</p>
  </div>
</div>
"""


def main():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1)
        with tempfile.TemporaryDirectory() as tmp:  # a file:// page, so the local fonts, CSS and shots load
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
