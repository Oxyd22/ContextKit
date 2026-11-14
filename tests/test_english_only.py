"""Tracked text files stay free of German umlauts, except REVIEW*.md."""
import os
import subprocess
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
# U+00E4 U+00F6 U+00FC U+00C4 U+00D6 U+00DC U+00DF — kept as code points so this
# file itself stays free of those letters.
UMLAUTS = "".join(chr(n) for n in (0xE4, 0xF6, 0xFC, 0xC4, 0xD6, 0xDC, 0xDF))
SUFFIXES = (".py", ".md", ".json")


def listed_files():
    """Files git knows about; falls back to a directory walk outside a git repo."""
    try:
        proc = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        names = []
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__")]
            for fn in filenames:
                names.append(os.path.relpath(os.path.join(dirpath, fn), ROOT))
        return names
    names = []
    for raw in proc.stdout.split(b"\0"):
        if raw:
            names.append(raw.decode("utf-8"))
    return names


class EnglishOnlyTests(unittest.TestCase):
    def test_no_umlauts_outside_review_notes(self):
        names = listed_files()
        offenders = []
        for name in names:
            if not name.endswith(SUFFIXES):
                continue
            base = os.path.basename(name)
            if base.startswith("REVIEW") and name.endswith(".md"):
                continue
            path = os.path.join(ROOT, name)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            if any(ch in text for ch in UMLAUTS):
                offenders.append(name)
        self.assertEqual(offenders, [])
