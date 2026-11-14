"""Doctor: platform Xcode check, and the INDEX anchor."""
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

import doctor  # noqa: E402


def isolated_env(home):
    os.makedirs(home, exist_ok=True)
    env = os.environ.copy()
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(key, None)
    env["HOME"] = home
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


NOTE = """---
id: NOTE-1
type: note
summary: hello
---

body
"""


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "home")
        self.proj = os.path.join(self.tmp.name, "proj")
        os.makedirs(self.proj)
        self.env = isolated_env(self.home)
        copy_project(self.proj)
        self.cfg_path = os.path.join(self.proj, ".claude", "contextkit", "contextkit.config.json")
        self.xcode = os.path.join(self.proj, "Foo.xcodeproj")

    def tearDown(self):
        self.tmp.cleanup()

    def _set_platform(self, platform):
        with open(self.cfg_path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["platform"] = platform
        data["references"] = {"path": "refs", "repos": []}
        data["knowledge"] = {"path": "knowledge", "ignore": ["README.md"]}
        with open(self.cfg_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
            fh.write("\n")

    def _doctor(self):
        return run_script(self.proj, self.env, "doctor.py")

    def _cfg(self):
        with open(self.cfg_path, encoding="utf-8") as fh:
            data = json.load(fh)
        home = os.path.join(self.proj, ".claude", "contextkit")
        return {
            "isHub": False,
            "root": self.proj,
            "configPath": self.cfg_path,
            "ticketPattern": data["ticketPattern"],
            "platform": data["platform"],
            "referencesPath": os.path.join(self.proj, "refs"),
            "references": {"repos": []},
            "knowledgePath": os.path.join(self.proj, "knowledge"),
            "knowledge": {"ignore": ["README.md"]},
            "contextkitHome": home,
            "cachePath": os.path.join(home, "cache", "references"),
        }

    def _tally(self):
        results = doctor.run_checks(self._cfg())
        return (
            sum(sym == doctor.OK for sym, _t, _d in results),
            sum(sym == doctor.WARN for sym, _t, _d in results),
            sum(sym == doctor.FAIL for sym, _t, _d in results),
        )

    def test_xcode_check_runs_only_for_ios(self):
        self._set_platform("generic")
        proc = self._doctor()
        self.assertEqual(proc.returncode, 0, proc.stderr)

        os.makedirs(self.xcode)
        proc = self._doctor()
        self.assertEqual(proc.returncode, 0, proc.stderr)

        self._set_platform("ios")
        proc = self._doctor()
        self.assertEqual(proc.returncode, 0, proc.stderr)

        os.rmdir(self.xcode)
        proc = self._doctor()
        self.assertNotEqual(proc.returncode, 0)

        self._set_platform("generic")
        proc = self._doctor()
        self.assertEqual(proc.returncode, 0, proc.stderr)

        self._set_platform("gadget")
        proc = self._doctor()
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_doctor_reads_index_anchor(self):
        self._set_platform("generic")
        kb = os.path.join(self.proj, "knowledge")
        os.makedirs(kb)
        with open(os.path.join(kb, "NOTE-1.md"), "w", encoding="utf-8") as fh:
            fh.write(NOTE)
        built = run_script(self.proj, self.env, "knowledge.py")
        self.assertEqual(built.returncode, 0, built.stderr)
        index_path = os.path.join(kb, "INDEX.md")
        with open(index_path, encoding="utf-8") as fh:
            good = fh.read()
        self.assertEqual(doctor.parse_index_entries(good), 1)
        self.assertIsNone(doctor.parse_index_entries("# Knowledge Index — 1 entries\n"))

        proc = self._doctor()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        ok_n, warn_n, fail_n = self._tally()
        self.assertEqual(fail_n, 0)

        with open(index_path, "w", encoding="utf-8") as fh:
            fh.write(good.replace(
                "<!-- contextkit:entries=1 -->",
                "<!-- contextkit:entries=99 -->",
            ))
        mismatched = self._doctor()
        self.assertEqual(mismatched.returncode, 0, mismatched.stderr)
        ok_bad, warn_bad, fail_bad = self._tally()
        self.assertEqual(fail_bad, fail_n)
        self.assertEqual(warn_bad, warn_n + 1)
        self.assertEqual(ok_bad, ok_n - 1)

        with open(index_path, "w", encoding="utf-8") as fh:
            fh.write(good.replace("<!-- contextkit:entries=1 -->\n", ""))
        missing = self._doctor()
        self.assertEqual(missing.returncode, 0, missing.stderr)
        _ok_miss, warn_miss, fail_miss = self._tally()
        self.assertEqual(fail_miss, 0)
        self.assertEqual(warn_miss, warn_n + 1)


if __name__ == "__main__":
    unittest.main()
