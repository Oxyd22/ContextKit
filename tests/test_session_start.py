"""session-start.py prints a branch ticket id and stays quiet otherwise."""
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


def git(env, cwd, *args):
    proc = subprocess.run(
        ["git", *args], cwd=cwd, env=env, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise AssertionError((proc.stderr or proc.stdout or "git failed").strip())
    return proc.stdout.strip()


def copy_project(dest):
    shutil.copytree(KIT, os.path.join(dest, ".claude", "contextkit"))
    hub = os.path.join(dest, ".claude", "contextkit", ".hub")
    if os.path.exists(hub):
        os.remove(hub)


class SessionStartTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "home")
        self.proj = os.path.join(self.tmp.name, "proj")
        os.makedirs(self.proj)
        self.env = isolated_env(self.home)
        copy_project(self.proj)
        git(self.env, self.proj, "init")

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self):
        script = os.path.join(self.proj, ".claude", "contextkit", "scripts", "session-start.py")
        return subprocess.run(
            [sys.executable, script],
            cwd=self.proj, env=self.env, capture_output=True, text=True,
        )

    def test_feature_branch_prints_ticket_id(self):
        git(self.env, self.proj, "checkout", "-b", "feature/ABC-123-x")
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("ABC-123", proc.stdout)
        self.assertNotIn("ABC-123-x", proc.stdout)

    def test_branch_without_ticket_is_silent(self):
        git(self.env, self.proj, "checkout", "-b", "feature/no-ticket")
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "")
        self.assertEqual(proc.stderr, "")


if __name__ == "__main__":
    unittest.main()
