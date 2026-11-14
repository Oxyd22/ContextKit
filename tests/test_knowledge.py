"""Knowledge parser, lint, index, ignore list, and orphan threshold."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
KIT = os.path.join(ROOT, ".claude", "contextkit")
SCRIPTS = os.path.join(KIT, "scripts")
sys.path.insert(0, SCRIPTS)

import knowledge  # noqa: E402


def isolated_env(home):
    os.makedirs(home, exist_ok=True)
    xdg = os.path.join(home, "xdg")
    os.makedirs(xdg, exist_ok=True)
    gitconfig = os.path.join(home, "gitconfig")
    with open(gitconfig, "w", encoding="utf-8") as fh:
        fh.write(
            "[user]\n\tname = ContextKit Test\n\temail = test@example.com\n"
            "[init]\n\tdefaultBranch = main\n"
            "[safe]\n\tdirectory = *\n"
        )
    env = os.environ.copy()
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(key, None)
    env["HOME"] = home
    env["XDG_CONFIG_HOME"] = xdg
    env["GIT_CONFIG_GLOBAL"] = gitconfig
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def copy_project(dest):
    shutil.copytree(KIT, os.path.join(dest, ".claude", "contextkit"))
    hub = os.path.join(dest, ".claude", "contextkit", ".hub")
    if os.path.exists(hub):
        os.remove(hub)


def write_cfg(proj, obj):
    path = os.path.join(proj, ".claude", "contextkit", "contextkit.config.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2)
        fh.write("\n")


def run_script(proj, env, name, *args):
    script = os.path.join(proj, ".claude", "contextkit", "scripts", name)
    return subprocess.run(
        [sys.executable, script, *args],
        cwd=proj,
        env=env,
        capture_output=True,
        text=True,
    )


NOTE = """---
id: {stem}
type: note
summary: {summary}
---

body
"""

DEC = """---
id: DEC-3            # stable key
type: decision      # note | decision | ticket
status: accepted    # only decision
summary: One sentence.  # max 120
related:
  - "[[DEC-1]]"  # first
  - DEC-2.md  # second
updated: 2024-01-02  # date
---

body
"""


class ParseTests(unittest.TestCase):
    def test_inline_comments_outside_quotes(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "DEC-3.md")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(DEC)
            fm = knowledge.parse_frontmatter(path)
        self.assertEqual(fm["id"], "DEC-3")
        self.assertEqual(fm["type"], "decision")
        self.assertEqual(fm["status"], "accepted")
        self.assertEqual(fm["summary"], "One sentence.")
        self.assertEqual(fm["updated"], "2024-01-02")
        self.assertEqual(fm["related"], ["[[DEC-1]]", "DEC-2.md"])
        self.assertEqual(knowledge.related_ids(fm), ["DEC-1", "DEC-2"])

    def test_hash_inside_quotes_is_kept(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "N.md")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write('---\nsummary: "keep # this"  # drop\nid: N\n---\n')
            fm = knowledge.parse_frontmatter(path)
        self.assertEqual(fm["summary"], "keep # this")
        self.assertEqual(fm["id"], "N")

    def test_hash_without_space_is_kept(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "N.md")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("---\nsummary: foo#bar\n---\n")
            fm = knowledge.parse_frontmatter(path)
        self.assertEqual(fm["summary"], "foo#bar")


class LintTests(unittest.TestCase):
    def setUp(self):
        self._kb = knowledge.KB
        self._index = knowledge.INDEX
        self._log = knowledge.LOG
        self.tmp = tempfile.TemporaryDirectory()
        knowledge.KB = self.tmp.name
        knowledge.INDEX = os.path.join(self.tmp.name, "INDEX.md")
        knowledge.LOG = os.path.join(self.tmp.name, "LOG.md")

    def tearDown(self):
        knowledge.KB = self._kb
        knowledge.INDEX = self._index
        knowledge.LOG = self._log
        self.tmp.cleanup()

    def _write(self, stem, summary="s"):
        with open(os.path.join(self.tmp.name, stem + ".md"), "w", encoding="utf-8") as fh:
            fh.write(NOTE.format(stem=stem, summary=summary))

    def test_missing_required_field_is_an_error(self):
        with open(os.path.join(self.tmp.name, "A.md"), "w", encoding="utf-8") as fh:
            fh.write("---\nid: A\ntype: note\n---\n")
        errs, _warns = knowledge.lint()
        self.assertEqual(len(errs), 1)

    def test_orphan_warns_only_from_three_entries(self):
        self._write("A")
        errs, warns = knowledge.lint()
        self.assertEqual(errs, [])
        self.assertEqual(warns, [])
        self._write("B")
        errs, warns = knowledge.lint()
        self.assertEqual(errs, [])
        self.assertEqual(warns, [])
        self._write("C")
        errs, warns = knowledge.lint()
        self.assertEqual(errs, [])
        self.assertEqual(len(warns), 3)

    def test_valid_decision_with_comments_has_no_errors(self):
        with open(os.path.join(self.tmp.name, "DEC-3.md"), "w", encoding="utf-8") as fh:
            fh.write(DEC.replace("related:\n  - \"[[DEC-1]]\"  # first\n  - DEC-2.md  # second\n", ""))
        errs, warns = knowledge.lint()
        self.assertEqual(errs, [])
        self.assertEqual(warns, [])


class IndexScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "home")
        self.proj = os.path.join(self.tmp.name, "proj")
        os.makedirs(self.proj)
        self.env = isolated_env(self.home)
        copy_project(self.proj)
        write_cfg(self.proj, {
            "references": {"path": "refs", "repos": []},
            "knowledge": {"path": "knowledge"},
        })
        self.kb = os.path.join(self.proj, "knowledge")
        os.makedirs(self.kb)

    def tearDown(self):
        self.tmp.cleanup()

    def test_index_ignores_readme_and_strips_comments(self):
        with open(os.path.join(self.kb, "README.md"), "w", encoding="utf-8") as fh:
            fh.write("# README\n\nnot an entry\n")
        with open(os.path.join(self.kb, "NOTE-1.md"), "w", encoding="utf-8") as fh:
            fh.write(NOTE.format(stem="NOTE-1", summary="hello"))
        with open(os.path.join(self.kb, "DEC-3.md"), "w", encoding="utf-8") as fh:
            fh.write(
                "---\n"
                "id: DEC-3            # stable key\n"
                "type: decision      # note | decision | ticket\n"
                "status: accepted    # only decision\n"
                "summary: One sentence.  # max 120\n"
                "---\n\nbody\n"
            )
        proc = run_script(self.proj, self.env, "knowledge.py")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        index_path = os.path.join(self.kb, "INDEX.md")
        with open(index_path, "rb") as fh:
            first = fh.read()
        index = first.decode("utf-8")
        self.assertIn("- [[NOTE-1]] — hello", index)
        self.assertIn("- [[DEC-3]] (accepted) — One sentence.", index)
        self.assertIn("<!-- contextkit:entries=2 -->", index)
        self.assertNotIn("README", index)
        self.assertNotIn("max 120", index)
        self.assertNotIn("stable key", index)
        again = run_script(self.proj, self.env, "knowledge.py")
        self.assertEqual(again.returncode, 0, again.stderr)
        with open(index_path, "rb") as fh:
            self.assertEqual(fh.read(), first)

    def test_schema_error_does_not_write_index(self):
        with open(os.path.join(self.kb, "A.md"), "w", encoding="utf-8") as fh:
            fh.write("---\nid: A\ntype: note\n---\n")
        proc = run_script(self.proj, self.env, "knowledge.py")
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(os.path.exists(os.path.join(self.kb, "INDEX.md")))


if __name__ == "__main__":
    unittest.main()
