"""Offline checks of the page sections: their order, the nav targets, the FAQ in every language, the Demo poster and
its never-dead link, and the footer links read from site settings."""

import json
import re
import unittest
from pathlib import Path

from tests.test_web_look import webp_size

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
ORDER = ["how", "fleet", "try", "gauge", "dark", "cost-limits", "faq", "demo"]
NAV = ["how", "fleet", "try", "faq", "demo"]


def html():
    return (WEB / "index.html").read_text(encoding="utf-8")


def langs():
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((WEB / "lang").glob("*.json"))}


class Sections(unittest.TestCase):
    def test_sections_follow_the_story(self):
        ids = re.findall(r'<section class="[^"]*" id="([\w-]+)"', html())
        self.assertEqual(ids, ORDER)
        self.assertLess(html().find('class="hero"'), html().find('id="how"'))

    def test_ids_are_unique(self):
        # app.js finds its blocks by id; a section sharing an id with one of them gets wiped on render
        ids = re.findall(r'\sid="([\w-]+)"', html())
        self.assertEqual(sorted(set(ids)), sorted(ids), [i for i in ids if ids.count(i) > 1])

    def test_desktop_nav_and_phone_menu_jump_to_the_same_sections(self):
        page = html()
        desktop = re.search(r'<nav class="nav".*?</nav>', page, re.S)[0]
        phone = re.search(r'<nav class="mnav-panel".*?</nav>', page, re.S)[0]
        for nav in (desktop, phone):
            self.assertEqual(re.findall(r'href="#([\w-]+)"', nav), NAV)
        self.assertIn('<details class="mnav" id="mnav">', page)


class Faq(unittest.TestCase):
    def test_at_least_six_questions_answered_in_every_language(self):
        keys = re.findall(r'data-i18n="(faq\.q\d+)"', html())
        self.assertGreaterEqual(len(keys), 6)
        self.assertEqual(len(keys), html().count('<details><summary>'))
        for name, d in langs().items():
            for q in keys:
                a = q.replace(".q", ".a")
                self.assertTrue(d.get(q, "").strip(), f"{name}: {q}")
                self.assertTrue(d.get(a, "").strip(), f"{name}: {a}")

    def test_answers_carry_no_figures_and_only_code_markup(self):
        # Figures live in the cost block, read from web/measured.json; an answer that quoted one would go stale.
        for name, d in langs().items():
            for k, v in d.items():
                if k.startswith("faq."):
                    self.assertNotRegex(v, r"\d", f"{name}: {k}")
                    self.assertEqual(re.sub(r"</?code>", "", v).count("<"), 0, f"{name}: {k}")


class Demo(unittest.TestCase):
    def test_poster_is_a_small_sized_webp(self):
        tag = re.search(r'<img src="(img/demo-poster\.webp)" width="(\d+)" height="(\d+)"[^>]*>', html())
        self.assertIsNotNone(tag)
        path = WEB / tag[1]
        self.assertEqual(webp_size(path), (int(tag[2]), int(tag[3])))
        self.assertLessEqual(path.stat().st_size, 120 * 1024)
        self.assertRegex(tag[0], r'data-i18n-attr="alt:demo\.posterAlt"')

    def test_demo_link_falls_back_to_a_real_page_and_never_embeds(self):
        site = json.loads((WEB / "site.json").read_text(encoding="utf-8"))
        self.assertRegex(site["pages"]["outage"], r"^https://")
        self.assertRegex(site["pages"]["license"], r"^https://")
        video = site["links"]["video"]
        self.assertTrue(video is None or video.startswith("https://"))
        self.assertNotIn("<iframe", html())
        for d in langs().values():
            for k in ("demo.readme", "demo.watch", "foot.github", "foot.license"):
                self.assertTrue(d.get(k, "").strip(), k)


if __name__ == "__main__":
    unittest.main()
