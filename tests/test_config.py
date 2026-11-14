"""Config ignore-list and writer abort on invalid JSON."""
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

import contextkit_config as ck  # noqa: E402


def isolated_env(home):
    os.makedirs(home, exist_ok=True)
    xdg = os.path.join(home, "xdg")
    os.makedirs(xdg, exist_ok=True)
    env = os.environ.copy()
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(key, None)
    env["HOME"] = home
    env["XDG_CONFIG_HOME"] = xdg
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def copy_project(dest):
    shutil.copytree(KIT, os.path.join(dest, ".claude", "contextkit"))
    hub = os.path.join(dest, ".claude", "contextkit", ".hub")
    if os.path.exists(hub):
        os.remove(hub)


def run_script(proj, env, name, *args):
    script = os.path.join(proj, ".claude", "contextkit", "scripts", name)
    return subprocess.run(
        [sys.executable, script, *args],
        cwd=proj, env=env, capture_output=True, text=True,
    )


class ConfigUnitTests(unittest.TestCase):
    def test_knowledge_ignored_names(self):
        names = ck.knowledge_ignored({"knowledge": {"ignore": ["README.md", "NOTES.md"]}})
        self.assertEqual(names, {"INDEX.md", "LOG.md", "README.md", "NOTES.md"})
        as_string = ck.knowledge_ignored({"knowledge": {"ignore": "README.md"}})
        self.assertIn("README.md", as_string)
        self.assertIn("INDEX.md", as_string)
        self.assertIn("LOG.md", as_string)

    def test_loaded_defaults_ignore_readme(self):
        cfg = ck.load()
        self.assertIsNone(cfg["configError"])
        self.assertIn("README.md", ck.knowledge_ignored(cfg))

    def test_platform_defaults_to_generic_and_normalizes(self):
        self.assertEqual(ck.DEFAULTS["platform"], "generic")
        self.assertEqual(ck.KNOWN_PLATFORMS, ("generic", "ios", "android", "web"))
        cfg = ck.load()
        self.assertEqual(cfg["platform"], "generic")
        self.assertEqual(ck.normalize_platform("iOS"), "ios")
        self.assertEqual(ck.normalize_platform("  Android "), "android")
        self.assertEqual(ck.normalize_platform(""), "generic")
        self.assertEqual(ck.normalize_platform(None), "generic")
        self.assertEqual(ck.normalize_platform("  "), "generic")
        self.assertTrue(ck.valid_platform_token("my_platform"))
        self.assertTrue(ck.valid_platform_token("web-1"))
        self.assertFalse(ck.valid_platform_token("iOS"))
        self.assertFalse(ck.valid_platform_token(""))
        self.assertFalse(ck.valid_platform_token("web app"))
        self.assertFalse(ck.valid_platform_token(None))

    def test_abort_on_config_error_exits_2(self):
        with self.assertRaises(SystemExit) as caught:
            ck.abort_on_config_error({"configError": "bad", "configPath": "x"})
        self.assertEqual(caught.exception.code, 2)
        self.assertIsNone(ck.abort_on_config_error({"configError": None, "configPath": "x"}))


class WriterAbortTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "home")
        self.proj = os.path.join(self.tmp.name, "proj")
        os.makedirs(self.proj)
        self.env = isolated_env(self.home)
        copy_project(self.proj)
        self.cfg = os.path.join(self.proj, ".claude", "contextkit", "contextkit.config.json")
        with open(self.cfg, "w", encoding="utf-8") as fh:
            fh.write("{not json\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_knowledge_and_reindex_exit_2(self):
        knowledge = run_script(self.proj, self.env, "knowledge.py")
        reindex = run_script(self.proj, self.env, "reindex.py", "--no-pull")
        self.assertEqual(knowledge.returncode, 2)
        self.assertEqual(reindex.returncode, 2)
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "project-knowledge")))
        cache = os.path.join(self.proj, ".claude", "contextkit", "cache", "references")
        mds = [name for name in os.listdir(cache) if name.endswith(".md")]
        self.assertEqual(mds, [])
        with open(self.cfg, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "{not json\n")


if __name__ == "__main__":
    unittest.main()
