"""Offline checks of web/: language files, config wiring, no third-party loads, shape of the data the page reads."""

import json
import re
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"


def read(path):
    return path.read_text(encoding="utf-8")


def langs():
    return {p.stem: json.loads(read(p)) for p in sorted((WEB / "lang").glob("*.json"))}


def stylesheets():
    return {p.name: read(p) for p in sorted((WEB / "css").glob("*.css"))}


def js_sources():
    return {p.name: read(p) for p in sorted((WEB / "js").glob("*.js"))}


class LanguageFiles(unittest.TestCase):
    def test_en_and_ms_have_the_same_keys_and_no_empty_text(self):
        files = langs()
        self.assertEqual(set(files), {"en", "ms"})
        self.assertEqual(set(files["en"]), set(files["ms"]))
        for code, d in files.items():
            for k, v in d.items():
                self.assertTrue(isinstance(v, str) and v.strip(), f"{code}:{k} empty")

    def test_placeholders_match_between_languages(self):
        files = langs()
        for k, en in files["en"].items():
            self.assertEqual(sorted(re.findall(r"\{\w+\}", en)), sorted(re.findall(r"\{\w+\}", files["ms"][k])), k)

    def test_every_key_used_by_the_page_exists(self):
        en = langs()["en"]
        html = read(WEB / "index.html")
        used = set(re.findall(r'data-i18n(?:-html)?="([^"]+)"', html))
        for attr in re.findall(r'data-i18n-attr="([^"]+)"', html):
            used |= {pair.split(":")[1] for pair in attr.split(";")}
        for src in js_sources().values():
            used |= set(re.findall(r'\bt\("([\w.]+)"', src))
            used |= {f"event.{e}" for e in re.findall(r'"(WentDark|Refueled|RefuelRequested|Relit)"', src)}
        self.assertTrue(used)
        self.assertEqual(sorted(used - set(en)), [])

    def test_event_labels_cover_every_event_the_indexer_reads(self):
        en = langs()["en"]
        events = json.loads(read(ROOT / "config" / "events.json"))
        names = {sig.split("(")[0] for role in ("keeper", "tank", "demo") for sig in events[role]}
        self.assertEqual(sorted(n for n in names if f"event.{n}" not in en), [])


class SiteConfig(unittest.TestCase):
    def setUp(self):
        self.site = json.loads(read(WEB / "site.json"))
        self.chains = json.loads(read(ROOT / "config" / "chains.json"))

    def test_site_points_at_real_config(self):
        self.assertIn(self.site["gauge_chain"], self.chains["chains"])
        self.assertIn(self.site["default_lang"], self.site["langs"])
        for code in self.site["langs"]:
            self.assertTrue((WEB / "lang" / f"{code}.json").is_file())
        for sel in ("debt(address)", "reserves(address)", "depositTo(address)"):
            self.assertIn(sel, self.chains["selectors"])
        int(self.site["gauge_fill_wei"])
        self.assertGreater(self.site["poll_seconds"], 0)

    def test_every_site_key_read_by_the_code_exists(self):
        src = "\n".join(js_sources().values())
        used = set(re.findall(r"\bsite\.(\w+)", src)) - {"json"}
        self.assertEqual(sorted(used - set(self.site)), [])


class NoThirdParty(unittest.TestCase):
    def test_no_remote_scripts_styles_or_fonts(self):
        html = read(WEB / "index.html")
        self.assertIsNone(re.search(r'<(script|link)[^>]+(src|href)="(https?:)?//', html))
        for css in stylesheets().values():
            self.assertIsNone(re.search(r"url\(\s*[\"']?(https?:)?//", css))
        for name, src in js_sources().items():
            self.assertIsNone(re.search(r"\bimport\b[^;]*['\"](https?:)?//", src), name)
            self.assertNotIn("document.cookie", src, name)

    def test_no_backdrop_filter_or_blur(self):
        for name, src in stylesheets().items():
            css = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
            self.assertFalse("backdrop-filter" in css, f"backdrop-filter in {name}")
            self.assertFalse(re.search(r"filter\s*:\s*blur", css), f"filter: blur in {name}")

    def test_stylesheet_comments_are_closed(self):
        for name, css in stylesheets().items():
            self.assertEqual(css.count("/*"), css.count("*/"), name)
        live = re.sub(r"/\*.*?\*/", "", read(WEB / "css" / "site.css"), flags=re.S)
        for needed in ("@font-face", "var(--aksen)", ".glyph.is-dark"):
            self.assertIn(needed, live)

    def test_local_assets_exist(self):
        css = read(WEB / "css" / "site.css")
        for rel in re.findall(r'url\("\.\./([^"]+)"\)', css):
            self.assertTrue((WEB / rel).is_file(), rel)
        for size in (64, 512):
            self.assertTrue((ROOT / "brand" / f"logo-{size}.png").is_file())
        self.assertTrue((WEB / "fonts" / "LICENSES.md").is_file())


class LinkPreview(unittest.TestCase):
    """PRD 4.7: a preview card under 300 KB, and robots that let preview crawlers read the page."""

    def test_card_is_a_small_png_of_the_size_the_page_declares(self):
        card = ROOT / "brand" / "og-card.png"
        data = card.read_bytes()
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", data[16:24])
        html = read(WEB / "index.html")
        self.assertIn(f'og:image:width" content="{width}"', html)
        self.assertIn(f'og:image:height" content="{height}"', html)
        self.assertLess(len(data), 300_000)

    def test_page_carries_the_preview_tags(self):
        html = read(WEB / "index.html")
        for tag in ('property="og:image"', 'property="og:url"', 'property="og:title"', 'name="twitter:card"', 'rel="canonical"'):
            self.assertIn(tag, html)
        self.assertRegex(html, r'property="og:image" content="@SITE@/brand/og-card\.png')

    def test_robots_turns_no_crawler_away(self):
        robots = read(WEB / "robots.txt")
        self.assertRegex(robots, r"(?m)^User-agent: \*$")
        self.assertNotRegex(robots, r"(?m)^Disallow:\s*/")

    def test_robots_names_each_preview_crawler_in_an_allowed_group(self):
        groups = [g for g in read(WEB / "robots.txt").split("\n\n") if "User-agent:" in g]
        preview = next(g for g in groups if "facebookexternalhit" in g)
        for bot in ("facebookexternalhit", "Facebot", "WhatsApp", "Twitterbot", "LinkedInBot", "TelegramBot",
                    "Slackbot", "Discordbot"):
            self.assertRegex(preview, rf"(?m)^User-agent: {bot}$")
        self.assertRegex(preview, r"(?m)^Allow: /$")
        self.assertNotIn("Disallow", preview)


class SnapshotShape(unittest.TestCase):
    """The page reads fields written by ops/indexer.py; the sample fixture must keep that shape."""

    def setUp(self):
        self.snap = json.loads(read(ROOT / "tests" / "fixtures" / "snapshot-sample.json"))

    def test_census_fields_read_by_the_page(self):
        c = self.snap["census"]["lasna"]
        for key in ("outages", "still_dark", "dark_age_seconds", "recovery_seconds", "dark", "to_block", "as_of_ts"):
            self.assertIn(key, c)
        for row in c["dark"]:
            self.assertEqual(set(row) >= {"address", "dark_seconds", "outages"}, True)

    def test_fleet_rows_match_indexer_rows(self):
        for view in self.snap["fleet"].values():
            self.assertIn(view["own"]["role"], ("keeper", "tank"))
            for w in view["wards"]:
                self.assertTrue({"address", "balance_wei", "debt_wei", "reserves_wei", "role", "name"} <= set(w))
                self.assertIn(w["role"], ("guarded", "control"))
        for e in self.snap["events"]:
            self.assertTrue({"chain", "event", "block", "tx"} <= set(e))


if __name__ == "__main__":
    unittest.main()
