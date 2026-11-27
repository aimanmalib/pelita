"""The READMEs and the BUIDL form text quote figures, addresses and hashes; each one must come from its source file.

- Every number in the README sections that quote results, and in all of docs/hantar/BUIDL.md, appears in
  docs/measured.md. A date written "November 4, 2026" must be an ISO date in measured.md.
- Every contract address in README.md and BUIDL.md is recorded in deployments/.
- Every transaction hash in README.md's loop list and in BUIDL.md is in the first-loops evidence file.

When report.py rewrites measured.md with new numbers, this test turns red until the READMEs are updated.
"""
import json
import re
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# README file -> headings of the sections whose numbers are quoted from measured.md
QUOTED = {
    "README.md": ["## For judges: the five-minute path", "## Measured results", "## Cost", "## How often contracts go dark"],
    "README.ms.md": ["## Hasil diukur", "## Berapa kerap kontrak padam"],
    "docs/hantar/BUIDL.md": [None],  # None = the whole file
}
# Files whose every address and transaction hash must be recorded (README.md: the loop section only, see below)
QUOTING_CHAIN = ["README.md", "docs/hantar/BUIDL.md"]
DATE = re.compile(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, \d{4}\b")
NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])")
ISO_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T[\d:]+Z")
LINK_TARGET = re.compile(r"\]\([^)]*\)")
HEX = re.compile(r"0x[0-9a-fA-F]+")
ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}(?![0-9a-fA-F])")
TX_HASH = re.compile(r"0x[0-9a-fA-F]{64}(?![0-9a-fA-F])")


def section(text, heading):
    if heading is None:
        return text
    start = text.index(heading + "\n")
    nxt = text.find("\n## ", start + len(heading))
    return text[start + len(heading): nxt if nxt != -1 else len(text)]


def iso_dates(text):
    return {datetime.strptime(d, "%B %d, %Y").strftime("%Y-%m-%d") for d in DATE.findall(text)}


def numbers(text):
    text = DATE.sub(" ", text)
    text = ISO_TIME.sub(" ", text)
    text = LINK_TARGET.sub("]", text)
    text = HEX.sub(" ", text)
    text = re.sub(r"\b(?:H\d+|E-\d+|ADR \d+)\b", " ", text)  # measure, evidence and decision labels are names
    text = re.sub(r"\ba 20\d\d winner\b", " ", text)  # the prior-art year ("Reactivate, a 2025 winner") is not a result
    return set(NUMBER.findall(text))


class ReadmeFigures(unittest.TestCase):
    def test_numbers_come_from_measured_md(self):
        measured_raw = (ROOT / "docs" / "measured.md").read_text()
        measured = numbers(measured_raw)
        for name, headings in QUOTED.items():
            text = (ROOT / name).read_text()
            for heading in headings:
                with self.subTest(file=name, section=heading):
                    quoted = numbers(section(text, heading))
                    self.assertTrue(quoted, "section quotes no figure; update QUOTED")
                    self.assertEqual(quoted - measured, set(), "figures not in docs/measured.md")
                    for iso in iso_dates(section(text, heading)):
                        self.assertIn(iso, measured_raw, "date not in docs/measured.md")

    def test_addresses_are_deployed(self):
        recorded = set()
        for f in (ROOT / "deployments").glob("*.json"):
            recorded |= {a.lower() for a in ADDRESS.findall(f.read_text())}
        for name in QUOTING_CHAIN:
            with self.subTest(file=name):
                quoted = {a.lower() for a in ADDRESS.findall((ROOT / name).read_text())}
                self.assertTrue(quoted)
                self.assertEqual(quoted - recorded, set(), "address not in deployments/")

    def test_loop_hashes_are_in_evidence(self):
        loops = json.loads((ROOT / "docs" / "evidence" / "E-004-first-loops.json").read_text())
        recorded = {s["tx"].lower() for loop in loops["loops"] for s in loop["steps"]}
        texts = {
            "README.md": section((ROOT / "README.md").read_text(), "## Deployment and full loops"),
            "docs/hantar/BUIDL.md": (ROOT / "docs" / "hantar" / "BUIDL.md").read_text(),
        }
        for name, text in texts.items():
            with self.subTest(file=name):
                quoted = {h.lower() for h in TX_HASH.findall(text)}
                self.assertGreaterEqual(len(quoted), 8)
                self.assertEqual(quoted - recorded, set(), "loop hash not in E-004 first loops")


if __name__ == "__main__":
    unittest.main()
