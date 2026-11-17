"""scripts/check-links.py: relative links and anchors in Markdown, checked offline."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("check_links", ROOT / "scripts" / "check-links.py")
check_links = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_links)


class CheckLinksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        (self.root / "docs").mkdir()
        (self.root / "docs" / "measured.md").write_text("# Measured\n\n## H1. Lasna `outages`\n\n## Repeat\n## Repeat\n")
        (self.root / "logo.png").write_bytes(b"png")

    def tearDown(self):
        self.tmp.cleanup()

    def run_check(self, text):
        f = self.root / "README.md"
        f.write_text(text)
        return check_links.check(f, root=self.root)

    def test_good_links_pass(self):
        text = ("# Top\n## For judges: the five-minute path\n"
                "[a](docs/measured.md) [b](docs/measured.md#h1-lasna-outages) [c](#for-judges-the-five-minute-path)\n"
                '<img src="logo.png"> [web](https://example.org/x) [d](docs/measured.md#repeat-1)\n')
        self.assertEqual(self.run_check(text), [])

    def test_missing_file_is_reported_with_line(self):
        problems = self.run_check("# T\n\n[x](docs/nope.md)\n")
        self.assertEqual(len(problems), 1)
        self.assertIn("README.md:3: docs/nope.md (no such file)", problems[0])

    def test_missing_anchor_is_reported(self):
        problems = self.run_check("[x](docs/measured.md#h9)\n[y](#gone)\n")
        self.assertEqual(len(problems), 2)
        self.assertIn("no heading for #h9", problems[0])
        self.assertIn("no heading for #gone", problems[1])

    def test_links_in_code_are_ignored(self):
        self.assertEqual(self.run_check("```\n[x](nope.md)\n```\n`[y](nope.md)`\n"), [])

    def test_link_outside_repository_is_reported(self):
        self.assertIn("outside the repository", self.run_check("[x](../../etc/passwd)\n")[0])

    def test_slug_matches_github(self):
        self.assertEqual(check_links.slug("Verify without trusting this README"), "verify-without-trusting-this-readme")
        self.assertEqual(check_links.slug("`REACT` cost, per relight (H5)"), "react-cost-per-relight-h5")


if __name__ == "__main__":
    unittest.main()
