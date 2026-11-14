"""setup.py --create-knowledge and --ticket-pattern."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
KIT = os.path.join(ROOT, ".claude", "contextkit")


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


def run_setup(proj, env, *args):
    script = os.path.join(proj, ".claude", "contextkit", "scripts", "setup.py")
    return subprocess.run(
        [sys.executable, script, *args],
        cwd=proj, env=env, capture_output=True, text=True,
    )


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "home")
        self.proj = os.path.join(self.tmp.name, "proj")
        os.makedirs(self.proj)
        self.env = isolated_env(self.home)
        copy_project(self.proj)
        self.cfg = os.path.join(self.proj, ".claude", "contextkit", "contextkit.config.json")

    def tearDown(self):
        self.tmp.cleanup()

    def _assert_repo(self, path):
        proc = subprocess.run(
            ["git", "-C", path, "rev-parse", "--is-inside-work-tree"],
            env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "true")

    def test_create_knowledge_inits_git(self):
        proc = run_setup(
            self.proj, self.env,
            "--write", "--references-path", "refs", "--knowledge-path", "knowledge",
            "--create-knowledge",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        know = os.path.join(self.proj, "knowledge")
        self._assert_repo(know)
        again = run_setup(
            self.proj, self.env,
            "--write", "--references-path", "refs", "--knowledge-path", "knowledge",
            "--create-knowledge",
        )
        self.assertEqual(again.returncode, 0, again.stderr)
        self._assert_repo(know)

    def test_create_knowledge_inits_existing_directory(self):
        know = os.path.join(self.proj, "knowledge")
        os.makedirs(know)
        self.assertFalse(os.path.exists(os.path.join(know, ".git")))
        proc = run_setup(
            self.proj, self.env,
            "--write", "--references-path", "refs", "--knowledge-path", "knowledge",
            "--create-knowledge",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self._assert_repo(know)

    def test_invalid_ticket_pattern_is_rejected(self):
        with open(self.cfg, "rb") as fh:
            before = fh.read()
        proc = run_setup(
            self.proj, self.env,
            "--write", "--references-path", "refs", "--knowledge-path", "knowledge",
            "--ticket-pattern", "[", "--create-knowledge",
        )
        self.assertNotEqual(proc.returncode, 0)
        with open(self.cfg, "rb") as fh:
            self.assertEqual(fh.read(), before)
        self.assertFalse(os.path.exists(os.path.join(self.proj, "knowledge")))

    def test_valid_ticket_pattern_is_stored(self):
        pattern = r"[A-Z]{2}-\d+"
        proc = run_setup(
            self.proj, self.env,
            "--write", "--references-path", "refs", "--knowledge-path", "knowledge",
            "--ticket-pattern", pattern,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(self.cfg, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["ticketPattern"], pattern)
        self.assertEqual(data["knowledge"]["path"], "knowledge")
        self.assertEqual(data["references"]["repos"], [])

    def test_platform_default_and_written_value(self):
        with open(self.cfg, encoding="utf-8") as fh:
            data = json.load(fh)
        data.pop("platform", None)
        with open(self.cfg, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
            fh.write("\n")
        omitted = run_setup(
            self.proj, self.env,
            "--write", "--references-path", "refs", "--knowledge-path", "knowledge",
        )
        self.assertEqual(omitted.returncode, 0, omitted.stderr)
        with open(self.cfg, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["platform"], "generic")

        written = run_setup(
            self.proj, self.env,
            "--write", "--references-path", "refs", "--knowledge-path", "knowledge",
            "--platform", "  web  ",
        )
        self.assertEqual(written.returncode, 0, written.stderr)
        with open(self.cfg, encoding="utf-8") as fh:
            stored = json.load(fh)
        self.assertEqual(stored["platform"], "web")
        self.assertEqual(stored["knowledge"]["path"], "knowledge")

    def test_invalid_platform_is_rejected(self):
        with open(self.cfg, "rb") as fh:
            before = fh.read()
        for value in ("", "iOS", "web app", "android/ios"):
            proc = run_setup(
                self.proj, self.env,
                "--write", "--references-path", "refs", "--knowledge-path", "knowledge",
                "--platform", value, "--create-knowledge",
            )
            self.assertNotEqual(proc.returncode, 0, value)
            with open(self.cfg, "rb") as fh:
                self.assertEqual(fh.read(), before, value)
        self.assertFalse(os.path.exists(os.path.join(self.proj, "knowledge")))

    def test_scan_accepts_platform_without_writing(self):
        with open(self.cfg, "rb") as fh:
            before = fh.read()
        ok = run_setup(
            self.proj, self.env,
            "--scan", "--references-path", "refs", "--platform", "android",
        )
        self.assertEqual(ok.returncode, 0, ok.stderr)
        with open(self.cfg, "rb") as fh:
            self.assertEqual(fh.read(), before)
        bad = run_setup(
            self.proj, self.env,
            "--scan", "--references-path", "refs", "--platform", "NO",
        )
        self.assertNotEqual(bad.returncode, 0)
        with open(self.cfg, "rb") as fh:
            self.assertEqual(fh.read(), before)


if __name__ == "__main__":
    unittest.main()
