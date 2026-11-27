"""The demo video quotes figures in its narration and on screen; each one must come from docs/measured.md.

Checked: every number in the narration lines (docs/media/video/skrip.json "sari") and in the on-screen text
(docs/media/video/garis.json "teks"). A census date written as "Nov 4, 2026" must match an ISO date in measured.md.
Step labels ("1 · …") are ordinals, not figures. When measured.md changes, this turns red until the video is redone.
"""
import json
import re
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIDEO = ROOT / "docs" / "media" / "video"
NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])")
DATE = re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2}, \d{4}\b")
DATE_NO_YEAR = re.compile(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}\b")
STEP = re.compile(r"^\d+ · ")
LICENCE = re.compile(r"\bCC BY(?:-SA)? \d\.\d\b")  # a licence version, not a figure
ISO_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T[\d:]+Z")


def numbers(text):
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)  # 8,524,855 -> 8524855
    return set(NUMBER.findall(text))


class VideoFigures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.measured_raw = (ROOT / "docs" / "measured.md").read_text(encoding="utf-8")
        cls.measured = numbers(ISO_TIME.sub(" ", cls.measured_raw).replace("-", " "))
        cls.lines = [b["sari"] for b in json.loads((VIDEO / "skrip.json").read_text(encoding="utf-8"))["baris"]]
        cls.screen = list(json.loads((VIDEO / "garis.json").read_text(encoding="utf-8"))["teks"].values())

    def check(self, text):
        for d in DATE.findall(text):
            iso = datetime.strptime(d.replace("Sept", "Sep"), "%b %d, %Y").strftime("%Y-%m-%d")
            self.assertIn(iso, self.measured_raw, f"date {d!r} is not in measured.md")
        text = LICENCE.sub(" ", DATE.sub(" ", DATE_NO_YEAR.sub(" ", STEP.sub("", text))))
        missing = numbers(text) - self.measured
        self.assertFalse(missing, f"{text!r}: {sorted(missing)} not in measured.md")

    def test_narration_numbers_are_measured(self):
        self.assertTrue(self.lines)
        for line in self.lines:
            with self.subTest(line=line):
                self.check(line)

    def test_screen_numbers_are_measured(self):
        for text in self.screen:
            with self.subTest(text=text):
                self.check(text)

    def test_census_date_is_measured(self):
        dates = [d for t in self.lines + self.screen for d in DATE_NO_YEAR.findall(t) + DATE.findall(t)]
        self.assertTrue(dates, "the census line names its start date")
        for d in dates:
            month, day = d.split(",")[0].split()
            m = datetime.strptime(month[:3], "%b").month
            self.assertIn(f"-{m:02d}-{int(day):02d}T", self.measured_raw, d)


if __name__ == "__main__":
    unittest.main()
