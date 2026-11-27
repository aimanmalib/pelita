"""The READMEs quote figures, addresses and hashes; each one must come from its source file, not from memory.

- Every number in the README sections that quote results appears in docs/measured.md.
- Every contract address in README.md is recorded in deployments/.
- Every transaction hash in README.md's loop list is in the first-loops evidence file.

When report.py rewrites measured.md with new numbers, this test turns red until the READMEs are updated.
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# README file -> headings of the sections whose numbers are quoted from measured.md
QUOTED = {
    "README.md": ["## For judges: the five-minute path", "## Measured results", "## Cost", "## How often contracts go dark"],
    "README.ms.md": ["## Hasil diukur", "## Berapa kerap kontrak padam"],
}
NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])")
ISO_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T[\d:]+Z")
LINK_TARGET = re.compile(r"\]\([^)]*\)")
HEX = re.compile(r"0x[0-9a-fA-F]+")
ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}(?![0-9a-fA-F])")
TX_HASH = re.compile(r"0x[0-9a-fA-F]{64}(?![0-9a-fA-F])")


def section(text, heading):
    start = text.index(heading + "\n")
    nxt = text.find("\n## ", start + len(heading))
    return text[start + len(heading): nxt if nxt != -1 else len(text)]


def numbers(text):
    text = ISO_TIME.sub(" ", text)
    text = LINK_TARGET.sub("]", text)
    text = HEX.sub(" ", text)
    text = re.sub(r"\b(?:H\d+|E-\d+|ADR \d+)\b", " ", text)  # measure, evidence and decision labels are names
    return set(NUMBER.findall(text))


class ReadmeFigures(unittest.TestCase):
    def test_numbers_come_from_measured_md(self):
        measured = numbers((ROOT / "docs" / "measured.md").read_text())
        for name, headings in QUOTED.items():
            text = (ROOT / name).read_text()
            for heading in headings:
                with self.subTest(file=name, section=heading):
                    quoted = numbers(section(text, heading))
                    self.assertTrue(quoted, "section quotes no figure; update QUOTED")
                    self.assertEqual(quoted - measured, set(), "figures not in docs/measured.md")

    def test_addresses_are_deployed(self):
        recorded = set()
        for f in (ROOT / "deployments").glob("*.json"):
            recorded |= {a.lower() for a in ADDRESS.findall(f.read_text())}
        quoted = {a.lower() for a in ADDRESS.findall((ROOT / "README.md").read_text())}
        self.assertTrue(quoted)
        self.assertEqual(quoted - recorded, set(), "README address not in deployments/")

    def test_loop_hashes_are_in_evidence(self):
        loops = json.loads((ROOT / "docs" / "evidence" / "E-004-first-loops.json").read_text())
        recorded = {s["tx"].lower() for loop in loops["loops"] for s in loop["steps"]}
        text = section((ROOT / "README.md").read_text(), "## Deployment and full loops")
        quoted = {h.lower() for h in TX_HASH.findall(text)}
        self.assertGreaterEqual(len(quoted), 8)
        self.assertEqual(quoted - recorded, set(), "README loop hash not in E-004 first loops")


if __name__ == "__main__":
    unittest.main()
