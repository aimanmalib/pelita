#!/usr/bin/env python3
"""Take the product shots shown in the hero frames, and the two page images in the README, from the page itself.

Serves web/ from this working tree (config/ and brand/ beside it, as deploy/ does) with the live snapshot fetched
from the deployed site, so the shots show the current look over real data; the browser reads the Lasna RPC itself.
What to shoot comes from web/site.json "shots": the page section, the device or viewport, the output size and the
file names, for light and dark. Change those values, then run this again: nothing here holds a size or a path.

Host tool (Playwright with Chromium and WebKit, Pillow with WebP), not part of the offline gate;
tests/test_web_look.py checks the committed files against web/site.json.
    python3 scripts/product-shots.py [--site https://pelita.sasateguh.com/]
"""
import argparse
import functools
import http.server
import io
import json
import pathlib
import re
import sys
import threading
import urllib.request

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = json.loads((ROOT / "web" / "site.json").read_text(encoding="utf-8"))
MAX_WEBP = 120 * 1024  # the hero frames load before anything else: keep each file small
SCHEMES = {"light": "light", "dark": "dark"}


def default_site():
    env = (ROOT / "deploy" / "site.env").read_text(encoding="utf-8")
    return "https://" + re.search(r"^DOMAIN=(\S+)$", env, re.M)[1] + "/"


class Handler(http.server.SimpleHTTPRequestHandler):
    snapshot = b"{}"

    def translate_path(self, path):
        path = path.split("?", 1)[0]
        for prefix, base in (("/config/", ROOT / "config"), ("/brand/", ROOT / "brand")):
            if path.startswith(prefix):
                return str(base / path[len(prefix):])
        return str(ROOT / "web" / path.lstrip("/"))

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/" + SITE["snapshot_url"]:
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("cache-control", "no-store")
            self.end_headers()
            self.wfile.write(self.snapshot)
            return
        super().do_GET()

    def log_message(self, *args):
        pass


def open_page(p, url, device, viewport, scheme):
    if device:
        opts = dict(p.devices[device])
        browser = p.webkit.launch()
    else:
        opts = {"device_scale_factor": 1}
        browser = p.chromium.launch()
    opts["viewport"] = {"width": viewport[0], "height": viewport[1]}
    ctx = browser.new_context(**opts, color_scheme=scheme, reduced_motion="reduce", locale="en-GB")
    page = ctx.new_page()
    page.goto(url, wait_until="networkidle")
    page.wait_for_function("document.getElementById('proof').dataset.status !== 'muat'", timeout=20_000)
    page.evaluate("document.fonts.ready")
    # the hero frames pick their light or dark shot after the theme script runs: wait until what is chosen is decoded
    page.evaluate("Promise.all([...document.querySelectorAll('img:not([loading=lazy])')].map(i => i.decode().catch(() => null)))")
    page.wait_for_timeout(300)
    return browser, page


def grab(page, section):
    if section:
        page.evaluate("id => document.getElementById(id).scrollIntoView({block: 'start'})", section)
        page.wait_for_timeout(400)
    return Image.open(io.BytesIO(page.screenshot(type="png"))).convert("RGB")


def save_webp(img, path):
    for quality in (82, 76, 70, 64, 58):
        buf = io.BytesIO()
        img.save(buf, "WEBP", quality=quality, method=6)
        if buf.tell() <= MAX_WEBP:
            path.write_bytes(buf.getvalue())
            return quality
    raise SystemExit(f"{path.name}: still over {MAX_WEBP} bytes at the lowest quality")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default=default_site(), help="deployed site to read the live snapshot from")
    args = ap.parse_args()
    req = urllib.request.Request(args.site.rstrip("/") + "/" + SITE["snapshot_url"],
                                 headers={"user-agent": "pelita-product-shots"})  # the edge refuses Python's default agent
    with urllib.request.urlopen(req, timeout=20) as r:
        Handler.snapshot = r.read()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/"
    shots = SITE["shots"]
    jobs = []  # (device, viewport, scheme, section, size, path, kind)
    for key in ("desktop", "phone"):
        s = shots[key]
        for scheme, src in (("light", s["src"]), ("dark", s["src_dark"])):
            jobs.append((s["device"], s["viewport"], scheme, s["section"], (s["width"], s["height"]),
                         ROOT / "web" / src, "webp"))
    for s in shots["readme"]:
        jobs.append((s["device"], s["viewport"], SCHEMES[s["theme"]], None, (s["width"], s["height"]),
                     ROOT / s["src"], "png"))
    try:
        with sync_playwright() as p:
            for device, viewport, scheme, section, size, path, kind in jobs:
                browser, page = open_page(p, url, device, viewport, scheme)
                img = grab(page, section)
                browser.close()
                if img.size != size:
                    img = img.resize(size, Image.LANCZOS)
                if kind == "webp":
                    q = save_webp(img, path)
                    print(f"{path.relative_to(ROOT)} {size[0]}x{size[1]} q{q} {path.stat().st_size} bytes")
                else:
                    img.save(path, "PNG", optimize=True)
                    print(f"{path.relative_to(ROOT)} {size[0]}x{size[1]} {path.stat().st_size} bytes")
    finally:
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
