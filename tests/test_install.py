#!/usr/bin/env python3
"""Install/update behavior for ContextKit. Stdlib unittest only.

Every subprocess gets HOME pointed at a temp directory. Assertions cover
exit codes and files, not installer message text.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL = os.path.join(ROOT, ".claude", "contextkit", "scripts", "install.py")
HUB_VERSION_PATH = os.path.join(ROOT, ".claude", "contextkit", "VERSION")

BEGIN = "<!-- contextkit:begin -->"
END = "<!-- contextkit:end -->"


def hub_version():
    with open(HUB_VERSION_PATH, encoding="utf-8") as f:
        return f.read().strip()


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ck-install-")
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.target = os.path.join(self.tmp, "project")
        os.makedirs(self.target)
        self.git("init", "-q")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def env(self):
        env = os.environ.copy()
        env["HOME"] = self.home
        env["GIT_CONFIG_GLOBAL"] = os.path.join(self.home, "gitconfig")
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        return env

    def git(self, *args):
        subprocess.run(
            ["git", "-C", self.target, *args],
            env=self.env(),
            check=True,
            capture_output=True,
            text=True,
        )

    def run_install(self, *args, target=None):
        return subprocess.run(
            [sys.executable, INSTALL, target or self.target, *args],
            env=self.env(),
            capture_output=True,
            text=True,
        )

    def read(self, path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    def write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def skill_dir(self, name, global_scope=False):
        if global_scope:
            return os.path.join(self.home, ".claude", "skills", name)
        return os.path.join(self.target, ".claude", "skills", name)

    def marker(self, name, global_scope=False):
        return os.path.join(self.skill_dir(name, global_scope), ".contextkit-owned")

    def exclude_lines(self):
        path = os.path.join(self.target, ".git", "info", "exclude")
        return self.read(path).splitlines()

    def assert_no_leaked_files(self):
        for dirpath, dirnames, filenames in os.walk(self.target):
            self.assertNotIn("tests", dirnames)
            for filename in filenames:
                self.assertFalse(
                    filename.startswith("REVIEW"),
                    "leaked review file: %s" % os.path.join(dirpath, filename),
                )

    def session_hooks(self):
        path = os.path.join(self.target, ".claude", "settings.local.json")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        hooks = []
        for group in data.get("hooks", {}).get("SessionStart", []):
            for hook in group.get("hooks", []):
                hooks.append(hook)
        return data, hooks

    def test_fresh_install_and_update(self):
        version = hub_version()
        proc = self.run_install()
        self.assertEqual(proc.returncode, 0)

        ns = os.path.join(self.target, ".claude", "contextkit")
        self.assertEqual(self.read(os.path.join(ns, "VERSION")).strip(), version)
        self.assertFalse(os.path.exists(os.path.join(ns, ".hub")))
        self.assertFalse(os.path.exists(os.path.join(ns, "scripts", "install.py")))
        self.assertTrue(os.path.isdir(os.path.join(ns, "scripts")))
        self.assertTrue(os.path.isdir(os.path.join(ns, "cache", "references")))
        self.assert_no_leaked_files()

        local_doc = self.read(os.path.join(self.target, "CLAUDE.local.md"))
        self.assertIn(BEGIN, local_doc)
        self.assertIn(END, local_doc)
        self.assertLess(local_doc.find(BEGIN), local_doc.find(END))

        manifest_path = os.path.join(ns, ".installed.json")
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertEqual(manifest["skillsScope"], "local")
        self.assertIn("ck-doctor", manifest["skills"])
        self.assertEqual(self.read(self.marker("ck-doctor")).strip(), version)

        config_path = os.path.join(ns, "contextkit.config.json")
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
        config["keep-me"] = "yes"
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f)
        cache_file = os.path.join(ns, "cache", "references", "kept.md")
        self.write(cache_file, "cached\n")
        script = os.path.join(ns, "scripts", "doctor.py")
        self.write(script, self.read(script) + "\n# sentinel-script\n")

        # User text outside the markers survives; the block itself is rewritten.
        preface = "USER-PREFACE\n\n"
        suffix = "USER-SUFFIX\n"
        mutated = local_doc.replace("ContextKit", "ContextKit-CHANGED", 1)
        begin = mutated.find(BEGIN)
        end = mutated.find(END) + len(END)
        self.write(
            os.path.join(self.target, "CLAUDE.local.md"),
            preface + mutated[begin:end] + "\n" + suffix,
        )

        proc = self.run_install("--update")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(self.read(os.path.join(ns, "VERSION")).strip(), version)
        self.assertNotIn("sentinel-script", self.read(script))
        self.assertTrue(os.path.isfile(cache_file))
        with open(config_path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["keep-me"], "yes")

        refreshed = self.read(os.path.join(self.target, "CLAUDE.local.md"))
        self.assertTrue(refreshed.startswith("USER-PREFACE"))
        self.assertIn("USER-SUFFIX", refreshed)
        self.assertNotIn("ContextKit-CHANGED", refreshed)
        self.assertIn(BEGIN, refreshed)
        self.assertIn(END, refreshed)
        self.assertIn("**ContextKit**", refreshed)

        self.assertFalse(os.path.exists(os.path.join(self.home, ".claude", "skills", ".contextkit.json")))

    def test_unmarked_claude_local_stays(self):
        proc = self.run_install()
        self.assertEqual(proc.returncode, 0)
        path = os.path.join(self.target, "CLAUDE.local.md")
        self.write(path, "KEEP ME\nno markers here\n")
        proc = self.run_install("--update")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(self.read(path), "KEEP ME\nno markers here\n")

    def test_foreign_skill_untouched_and_marker_on_owned(self):
        version = hub_version()
        foreign = self.skill_dir("ck-doctor")
        self.write(os.path.join(foreign, "SKILL.md"), "FOREIGN-SKILL\n")
        proc = self.run_install()
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(self.read(os.path.join(foreign, "SKILL.md")), "FOREIGN-SKILL\n")
        self.assertFalse(os.path.exists(self.marker("ck-doctor")))
        self.assertEqual(self.read(self.marker("ck-read-note")).strip(), version)

        manifest_path = os.path.join(self.target, ".claude", "contextkit", ".installed.json")
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertNotIn("ck-doctor", manifest["skills"])
        self.assertIn("ck-read-note", manifest["skills"])

        proc = self.run_install("--update")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(self.read(os.path.join(foreign, "SKILL.md")), "FOREIGN-SKILL\n")
        self.assertFalse(os.path.exists(self.marker("ck-doctor")))
        self.assertTrue(os.path.isfile(self.marker("ck-read-note")))
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertNotIn("ck-doctor", manifest["skills"])

        lines = self.exclude_lines()
        self.assertIn("/.claude/settings.local.json", lines)
        self.assertIn("/.claude/contextkit/", lines)
        self.assertIn("/CLAUDE.local.md", lines)
        self.assertIn("/.claude/skills/ck-read-note/", lines)
        self.assertNotIn("/.claude/skills/ck-doctor/", lines)

    def test_legacy_adoption_overwrites_manifest_skill_without_marker(self):
        proc = self.run_install()
        self.assertEqual(proc.returncode, 0)
        skill = self.skill_dir("ck-read-note")
        os.remove(self.marker("ck-read-note"))
        self.write(os.path.join(skill, "EXTRA.txt"), "legacy-extra\n")
        hub_skill = self.read(os.path.join(ROOT, ".claude", "skills", "ck-read-note", "SKILL.md"))

        proc = self.run_install("--update")
        self.assertEqual(proc.returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(skill, "EXTRA.txt")))
        self.assertEqual(self.read(os.path.join(skill, "SKILL.md")), hub_skill)
        self.assertEqual(self.read(self.marker("ck-read-note")).strip(), hub_version())

    def test_global_downgrade_refused_unless_force(self):
        version = hub_version()
        proc = self.run_install("--skills-global")
        self.assertEqual(proc.returncode, 0)
        self.assertFalse(os.path.isdir(os.path.join(self.target, ".claude", "skills")))

        version_path = os.path.join(self.home, ".claude", "skills", ".contextkit.json")
        with open(version_path, encoding="utf-8") as f:
            recorded = json.load(f)
        self.assertEqual(recorded["version"], version)
        self.assertEqual(
            self.read(self.marker("ck-doctor", global_scope=True)).strip(),
            version,
        )

        lines = self.exclude_lines()
        self.assertIn("/.claude/settings.local.json", lines)
        self.assertNotIn("/.claude/skills/ck-doctor/", lines)

        # 1.0.0 is older than the hub: an upgrade is allowed and rewrites the record.
        skill_file = os.path.join(self.skill_dir("ck-doctor", global_scope=True), "SKILL.md")
        original = self.read(skill_file)
        recorded["version"] = "1.0.0"
        self.write(version_path, json.dumps(recorded))
        self.write(skill_file, "SENTINEL-OLD\n")
        proc = self.run_install("--update")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(self.read(skill_file), original)
        with open(version_path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["version"], version)

        # 2.10.0 is numerically newer than the hub version. A string compare would get this backwards.
        recorded = {"version": "2.10.0"}
        self.write(version_path, json.dumps(recorded) + "\n")
        self.write(skill_file, "SENTINEL-NEWER\n")
        target_version = os.path.join(self.target, ".claude", "contextkit", "VERSION")
        self.write(target_version, "0.0.0\n")
        proc = self.run_install("--update")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(self.read(skill_file), "SENTINEL-NEWER\n")
        self.assertEqual(self.read(target_version), "0.0.0\n")
        with open(version_path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["version"], "2.10.0")

        proc = self.run_install("--update", "--force")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(self.read(skill_file), original)
        self.assertEqual(self.read(target_version).strip(), version)
        with open(version_path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["version"], version)
        self.assertEqual(
            self.read(self.marker("ck-doctor", global_scope=True)).strip(),
            version,
        )

    def test_fresh_global_downgrade_refuses_before_writing(self):
        version_path = os.path.join(self.home, ".claude", "skills", ".contextkit.json")
        self.write(version_path, json.dumps({"version": "2.10.0"}) + "\n")
        sentinel = os.path.join(self.home, ".claude", "skills", "ck-setup", "SKILL.md")
        self.write(sentinel, "FOREIGN-GLOBAL\n")
        proc = self.run_install("--skills-global")
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(os.path.isdir(os.path.join(self.target, ".claude")))
        self.assertEqual(self.read(sentinel), "FOREIGN-GLOBAL\n")
        with open(version_path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["version"], "2.10.0")
        self.assertFalse(os.path.isdir(os.path.join(self.home, ".claude", "skills", "ck-doctor")))

    def test_hook_has_no_async_and_update_repairs_it(self):
        proc = self.run_install()
        self.assertEqual(proc.returncode, 0)
        data, hooks = self.session_hooks()
        contextkit_hooks = [
            h for h in hooks
            if "contextkit/scripts/session-start.py" in h.get("command", "")
        ]
        self.assertEqual(len(contextkit_hooks), 1)
        self.assertNotIn("async", contextkit_hooks[0])

        contextkit_hooks[0]["async"] = True
        data["customKept"] = True
        data["hooks"]["SessionStart"].append(
            {"hooks": [{"type": "command", "command": "echo kept"}]}
        )
        path = os.path.join(self.target, ".claude", "settings.local.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")

        proc = self.run_install("--update")
        self.assertEqual(proc.returncode, 0)
        data, hooks = self.session_hooks()
        self.assertTrue(data["customKept"])
        commands = [h.get("command", "") for h in hooks]
        self.assertIn("echo kept", commands)
        contextkit_hooks = [
            h for h in hooks
            if "contextkit/scripts/session-start.py" in h.get("command", "")
        ]
        self.assertEqual(len(contextkit_hooks), 1)
        self.assertNotIn("async", contextkit_hooks[0])

    def test_unknown_flag_and_exclusive_skills_flags(self):
        proc = self.run_install("--skill-global")
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(os.path.isdir(os.path.join(self.target, ".claude")))

        proc = self.run_install("--skills-global", "--skills-local")
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(os.path.isdir(os.path.join(self.target, ".claude")))

    def test_hub_target_refused(self):
        proc = self.run_install(target=ROOT)
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(
            os.path.exists(os.path.join(ROOT, ".claude", "contextkit", ".installed.json"))
        )

        link = os.path.join(self.tmp, "hub-link")
        os.symlink(ROOT, link)
        proc = self.run_install(target=link)
        self.assertNotEqual(proc.returncode, 0)

        nested = os.path.join(self.tmp, "hub-nested")
        os.symlink(os.path.join(ROOT, ".claude"), nested)
        proc = self.run_install(target=nested)
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(
            os.path.exists(os.path.join(ROOT, ".claude", "contextkit", ".installed.json"))
        )

    def test_scope_switch_removes_owned_local_skills_only(self):
        foreign = self.skill_dir("ck-doctor")
        self.write(os.path.join(foreign, "SKILL.md"), "FOREIGN-SKILL\n")
        proc = self.run_install()
        self.assertEqual(proc.returncode, 0)

        # A same-named global directory without a marker is not ours to replace,
        # even though the local manifest lists other skills.
        global_note = self.skill_dir("ck-read-note", global_scope=True)
        self.write(os.path.join(global_note, "SKILL.md"), "FOREIGN-GLOBAL-NOTE\n")

        proc = self.run_install("--update", "--skills-global")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(self.read(os.path.join(foreign, "SKILL.md")), "FOREIGN-SKILL\n")
        self.assertFalse(os.path.isdir(self.skill_dir("ck-read-note")))
        self.assertFalse(os.path.isdir(self.skill_dir("ck-setup")))
        self.assertEqual(self.read(os.path.join(global_note, "SKILL.md")), "FOREIGN-GLOBAL-NOTE\n")
        self.assertFalse(os.path.exists(self.marker("ck-read-note", global_scope=True)))
        self.assertTrue(os.path.isfile(self.marker("ck-doctor", global_scope=True)))
        self.assertTrue(os.path.isfile(self.marker("ck-setup", global_scope=True)))

        manifest_path = os.path.join(self.target, ".claude", "contextkit", ".installed.json")
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertEqual(manifest["skillsScope"], "global")
        self.assertNotIn("ck-read-note", manifest["skills"])
        self.assertIn("ck-doctor", manifest["skills"])

    def test_changelog_is_not_installed(self):
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "CHANGELOG.md")))
        proc = self.run_install()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(self._has_changelog())
        proc = self.run_install("--update")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(self._has_changelog())

    def _has_changelog(self):
        found = []
        for base in (self.target, self.home):
            for dirpath, _dirnames, filenames in os.walk(base):
                if "CHANGELOG.md" in filenames:
                    found.append(os.path.join(dirpath, "CHANGELOG.md"))
        return found


if __name__ == "__main__":
    unittest.main()
