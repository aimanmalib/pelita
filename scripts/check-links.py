#!/usr/bin/env python3
"""Offline link check for the repository's Markdown: every relative link points at a file that exists in the
repository, and every `#anchor` matches a heading in the target file (GitHub's slug rules). Web links are not
fetched, so the check runs the same in CI and without a network.

Usage: python3 scripts/check-links.py [FILE.md ...]   (default: the README files and the community files)
Exit code 1 lists each broken link as `file:line: link (reason)`.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = ["README.md", "README.ms.md", "CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md", "docs/SECURITY.md"]

LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
HTML = re.compile(r"""(?:href|src)=["']([^"']+)["']""")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")


def slug(text):
    """GitHub heading anchor: lower case, drop punctuation except hyphens and spaces, spaces become hyphens."""
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = text.strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(path):
    seen, out = {}, set()
    in_fence = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        m = None if in_fence else HEADING.match(line)
        if not m:
            continue
        base = slug(m.group(2))
        n = seen.get(base, 0)
        seen[base] = n + 1
        out.add(base if n == 0 else f"{base}-{n}")
    out.update(re.findall(r"""<a\s+(?:name|id)=["']([^"']+)["']""", path.read_text(encoding="utf-8")))
    return out


def links(path):
    in_fence = False
    for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        stripped = re.sub(r"`[^`]*`", "", line)
        for m in list(LINK.finditer(stripped)) + list(HTML.finditer(stripped)):
            yield no, m.group(1)


def check(path, root=ROOT):
    problems = []
    for no, link in links(path):
        if re.match(r"^[a-z][a-z0-9+.-]*:", link, re.I):
            continue  # https:, mailto: and friends are not fetched
        target, _, frag = link.partition("#")
        dest = path if not target else (path.parent / target).resolve()
        try:
            dest.relative_to(root.resolve())
        except ValueError:
            problems.append(f"{path.relative_to(root)}:{no}: {link} (outside the repository)")
            continue
        if not dest.exists():
            problems.append(f"{path.relative_to(root)}:{no}: {link} (no such file)")
            continue
        if frag and dest.suffix == ".md" and frag.lower() not in anchors(dest):
            problems.append(f"{path.relative_to(root)}:{no}: {link} (no heading for #{frag})")
    return problems


def main(argv):
    files = [ROOT / f for f in (argv or DEFAULT)]
    problems = []
    for f in files:
        if f.exists():
            problems += check(f)
        elif argv:
            problems.append(f"{f}: missing")
    for p in problems:
        print(p)
    print(f"check-links: {len(problems)} broken link(s) in {sum(f.exists() for f in files)} file(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
