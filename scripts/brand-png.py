#!/usr/bin/env python3
"""Render brand/logo.svg to brand/logo-512.png and brand/logo-64.png with headless Chromium.

Host tool (needs Playwright). Not part of the offline gate.
"""
import pathlib
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
SVG = ROOT / "brand" / "logo.svg"


def main():
    svg = SVG.read_text(encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for size in (512, 64):
            page = browser.new_page(viewport={"width": size, "height": size}, device_scale_factor=1)
            page.set_content(
                "<style>html,body{margin:0;background:transparent}svg{display:block;width:100vw;height:100vh}</style>" + svg
            )
            out = ROOT / "brand" / f"logo-{size}.png"
            page.screenshot(path=str(out), omit_background=True)
            print(out.relative_to(ROOT), out.stat().st_size)
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
