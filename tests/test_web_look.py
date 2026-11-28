"""Offline checks of the page look: generated tokens loaded first, colours only through tokens, two self-hosted
font families, no forced capitals, real product shots in the hero frames, theme applied before first paint."""

import json
import re
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
COLOUR_LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")


def read(path):
    return path.read_text(encoding="utf-8")


def live_css(path):
    return re.sub(r"/\*.*?\*/", "", read(path), flags=re.S)


def webp_size(path):
    """(width, height) of a lossy or lossless WebP file."""
    b = path.read_bytes()
    assert b[:4] == b"RIFF" and b[8:12] == b"WEBP", path
    kind = b[12:16]
    if kind == b"VP8 ":
        w, h = struct.unpack("<HH", b[26:30])
        return w & 0x3FFF, h & 0x3FFF
    if kind == b"VP8L":
        bits = int.from_bytes(b[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if kind == b"VP8X":
        return int.from_bytes(b[24:27], "little") + 1, int.from_bytes(b[27:30], "little") + 1
    raise AssertionError(f"unknown WebP chunk {kind!r} in {path}")


class Tokens(unittest.TestCase):
    def test_tokens_load_before_the_site_styles(self):
        html = read(WEB / "index.html")
        order = [m[1] for m in re.finditer(r'<link rel="stylesheet" href="css/([\w-]+)\.css"', html)]
        self.assertEqual(order[0], "token", order)
        self.assertIn("site", order)

    def test_no_colour_literals_outside_the_tokens(self):
        for path in sorted((WEB / "css").glob("*.css")):
            if path.name == "token.css":
                continue
            for line in live_css(path).splitlines():
                self.assertIsNone(COLOUR_LITERAL.search(line), f"{path.name}: {line.strip()}")

    def test_token_file_defines_both_themes(self):
        css = read(WEB / "css" / "token.css")
        for needed in ("--aksen:", "--latar:", "--teks:", ":root[data-tema=\"gelap\"]", "prefers-color-scheme: dark"):
            self.assertIn(needed, css)

    def test_no_forced_capitals(self):
        for path in sorted((WEB / "css").glob("*.css")):
            self.assertNotRegex(live_css(path), r"text-transform\s*:\s*uppercase", path.name)


class Fonts(unittest.TestCase):
    def test_exactly_two_self_hosted_families(self):
        faces = []
        for path in sorted((WEB / "css").glob("*.css")):
            for block in re.findall(r"@font-face\s*\{([^}]*)\}", live_css(path)):
                family = re.search(r"font-family:\s*\"?([^;\"]+)\"?", block)[1]
                src = re.search(r'url\("\.\./([^"]+)"\)', block)[1]
                self.assertTrue((WEB / src).is_file(), src)
                self.assertIn("font-display: swap", block)
                faces.append(family)
        self.assertEqual(sorted(faces), ["Figtree", "Geist Mono"])

    def test_no_other_font_files_are_served(self):
        files = sorted(p.name for p in (WEB / "fonts").glob("*.woff2"))
        self.assertEqual(files, ["figtree.woff2", "geist-mono.woff2"])
        licences = read(WEB / "fonts" / "LICENSES.md")
        for name in files:
            self.assertIn(name, licences)


class HeroShots(unittest.TestCase):
    def test_frames_show_the_shots_named_in_site_settings(self):
        site = json.loads(read(WEB / "site.json"))
        html = read(WEB / "index.html")
        for key in ("desktop", "phone"):
            shot = site["shots"][key]
            tag = re.search(rf'<img src="{re.escape(shot["src"])}"[^>]*>', html)
            self.assertIsNotNone(tag, shot["src"])
            self.assertIn(f'width="{shot["width"]}"', tag[0])
            self.assertIn(f'height="{shot["height"]}"', tag[0])
            self.assertNotIn('loading="lazy"', tag[0])
            self.assertRegex(tag[0], r'data-i18n-attr="alt:hero\.\w+"')
            for src in (shot["src"], shot["src_dark"]):
                path = WEB / src
                self.assertEqual(webp_size(path), (shot["width"], shot["height"]), src)
                self.assertLessEqual(path.stat().st_size, 120 * 1024, src)

    def test_each_frame_has_a_dark_shot_that_the_theme_switch_can_choose(self):
        site = json.loads(read(WEB / "site.json"))
        html = read(WEB / "index.html")
        for key in ("desktop", "phone"):
            shot = site["shots"][key]
            pic = re.search(rf'<picture>\s*(<source [^>]*>)\s*<img src="{re.escape(shot["src"])}"', html)
            self.assertIsNotNone(pic, key)
            self.assertIn(f'srcset="{shot["src_dark"]}"', pic[1])
            self.assertIn('media="(prefers-color-scheme: dark)"', pic[1])
            self.assertIn("data-shot-dark", pic[1])
        self.assertIn("source[data-shot-dark]", read(WEB / "js" / "theme.js"))

    def test_readme_page_images_match_site_settings(self):
        for shot in json.loads(read(WEB / "site.json"))["shots"]["readme"]:
            data = (ROOT / shot["src"]).read_bytes()
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(struct.unpack(">II", data[16:24]), (shot["width"], shot["height"]), shot["src"])


class Theme(unittest.TestCase):
    def test_saved_theme_applies_before_the_first_paint(self):
        html = read(WEB / "index.html")
        head = html.split("</head>")[0]
        boot = head.find('<script src="js/theme-boot.js"></script>')
        self.assertGreater(boot, 0, "theme-boot.js must load synchronously in <head>")
        self.assertLess(boot, head.find('<link rel="stylesheet"'))
        self.assertNotIn("<script>", html, "inline scripts are blocked by the Content-Security-Policy")

    def test_switch_has_a_name_in_every_language(self):
        for path in sorted((WEB / "lang").glob("*.json")):
            d = json.loads(read(path))
            for key in ("theme.toDark", "theme.toLight"):
                self.assertTrue(d.get(key, "").strip(), f"{path.name}: {key}")
        self.assertIn('id="theme"', read(WEB / "index.html"))


class Sections(unittest.TestCase):
    def test_demo_poster_loads_without_scrolling(self):
        """A lazy poster stays a black box in full-page captures (link previews, review screenshots)."""
        tag = re.search(r'<img src="img/demo-poster\.webp"[^>]*>', read(WEB / "index.html"))
        self.assertIsNotNone(tag)
        self.assertNotIn('loading="lazy"', tag[0])

    def test_fleet_pairs_share_a_row_on_wide_screens(self):
        """Lamps come as guarded + control pairs; a 3-column grid strands the fourth card on its own row."""
        css = live_css(WEB / "css" / "site.css")
        self.assertRegex(css, r"@media \(min-width: \d+px\) \{ \.cards \{ grid-template-columns: repeat\(2, minmax\(0, 1fr\)\); \} \}")
        self.assertNotIn("auto-fill, minmax(min(100%, 26rem)", css)


if __name__ == "__main__":
    unittest.main()
