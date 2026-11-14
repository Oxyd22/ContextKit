"""Reindex keeps the cache body, stores the full SHA, and pulls with a timeout."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
KIT = os.path.join(ROOT, ".claude", "contextkit")
SCRIPTS = os.path.join(KIT, "scripts")
sys.path.insert(0, SCRIPTS)

import reindex  # noqa: E402


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
    env["GIT_AUTHOR_NAME"] = "ContextKit Test"
    env["GIT_AUTHOR_EMAIL"] = "test@example.com"
    env["GIT_COMMITTER_NAME"] = "ContextKit Test"
    env["GIT_COMMITTER_EMAIL"] = "test@example.com"
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


def write_cfg(proj):
    path = os.path.join(proj, ".claude", "contextkit", "contextkit.config.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({
            "references": {"path": "refs", "repos": ["demo"]},
            "knowledge": {"path": "knowledge"},
        }, fh, indent=2)
        fh.write("\n")


def run_reindex(proj, env, *args):
    script = os.path.join(proj, ".claude", "contextkit", "scripts", "reindex.py")
    return subprocess.run(
        [sys.executable, script, *args],
        cwd=proj, env=env, capture_output=True, text=True,
    )


def cache_file(proj):
    return os.path.join(proj, ".claude", "contextkit", "cache", "references", "demo.md")


def split_body(text):
    marker = "\n---\n"
    start = text.find(marker)
    if not text.startswith("---\n") or start < 0:
        raise AssertionError("missing frontmatter")
    return text[start + len(marker):]


def fm_value(text, key):
    fm = text.split("\n---\n", 1)[0]
    prefix = key + ":"
    for line in fm.splitlines():
        if line.startswith(prefix):
            return line.split(":", 1)[1].strip()
    return None


class FrontmatterUnitTests(unittest.TestCase):
    def test_update_keeps_body_and_sets_status(self):
        sha = "a" * 40
        text = (
            "---\nrepo: demo\nsha: old\nstatus: indexed\n---\n"
            "\nKEEP-ME\nstatus: indexed\n"
        )
        new = reindex.update_frontmatter(text, sha)
        self.assertEqual(split_body(new), "\nKEEP-ME\nstatus: indexed\n")
        self.assertEqual(fm_value(new, "sha"), sha)
        self.assertEqual(fm_value(new, "status"), "needs-extraction")
        self.assertEqual(fm_value(new, "repo"), "demo")

    def test_cached_value_ignores_body(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "demo.md")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("---\nsha: from-fm\nstatus: indexed\n---\nsha: from-body\n")
            self.assertEqual(reindex.cached_value(path, "sha"), "from-fm")
            self.assertEqual(reindex.cached_value(path, "status"), "indexed")

    def test_pull_sets_timeout_and_prompt_env(self):
        with mock.patch.object(reindex.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess(["git"], 0, "", "")
            reindex.pull("/repos/demo")
        cmd = run.call_args.args[0]
        kwargs = run.call_args.kwargs
        self.assertEqual(cmd[:4], ["git", "-C", "/repos/demo", "pull"])
        self.assertIn("--ff-only", cmd)
        self.assertEqual(kwargs["timeout"], reindex.PULL_TIMEOUT)
        self.assertEqual(kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")

    def test_default_scope_names_keep_their_headings(self):
        self.assertEqual(
            [reindex.scope_heading(name, "ios", "demo")
             for name in ("contracts", "api-specs", "parity")],
            [
                "## Contracts / Public API",
                "## API-Specs / Endpoints",
                "## Parity (ios <-> demo)",
            ],
        )
        self.assertEqual(reindex.scope_heading("custom-thing", "web", "demo"), "## Custom Thing")

    def test_git_timeout_is_a_failed_result(self):
        with mock.patch.object(
            reindex.subprocess, "run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=120),
        ):
            proc = reindex.git("/repos/demo", "pull", timeout=120)
        self.assertNotEqual(proc.returncode, 0)


class ReindexGitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "home")
        self.proj = os.path.join(self.tmp.name, "proj")
        os.makedirs(self.proj)
        self.env = isolated_env(self.home)
        copy_project(self.proj)
        write_cfg(self.proj)
        self.repo = os.path.join(self.proj, "refs", "demo")
        os.makedirs(self.repo)
        git(self.env, self.repo, "init")
        with open(os.path.join(self.repo, "f.txt"), "w", encoding="utf-8") as fh:
            fh.write("v1\n")
        git(self.env, self.repo, "add", "f.txt")
        git(self.env, self.repo, "commit", "-m", "init")

    def tearDown(self):
        self.tmp.cleanup()

    def test_stores_full_sha_and_keeps_body_when_sha_changes(self):
        first = run_reindex(self.proj, self.env, "--no-pull")
        self.assertEqual(first.returncode, 0, first.stderr)
        path = cache_file(self.proj)
        full1 = git(self.env, self.repo, "rev-parse", "HEAD")
        short1 = git(self.env, self.repo, "rev-parse", "--short", "HEAD")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertEqual(fm_value(text, "sha"), full1)
        self.assertNotEqual(full1, short1)
        self.assertNotIn("sha: %s\n" % short1, text)
        text = text.replace("status: needs-extraction", "status: indexed", 1)
        text = text + "LIVE-FINDING-99\n"
        body_before = split_body(text)
        self.assertIn("LIVE-FINDING-99\n", body_before)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        with open(os.path.join(self.repo, "f.txt"), "a", encoding="utf-8") as fh:
            fh.write("v2\n")
        git(self.env, self.repo, "add", "f.txt")
        git(self.env, self.repo, "commit", "-m", "next")
        full2 = git(self.env, self.repo, "rev-parse", "HEAD")
        self.assertNotEqual(full1, full2)
        second = run_reindex(self.proj, self.env, "--no-pull")
        self.assertEqual(second.returncode, 0, second.stderr)
        with open(path, encoding="utf-8") as fh:
            updated = fh.read()
        self.assertEqual(split_body(updated), body_before)
        self.assertEqual(fm_value(updated, "sha"), full2)
        self.assertEqual(fm_value(updated, "status"), "needs-extraction")

    def test_unchanged_sha_does_not_rewrite_cache(self):
        proc = run_reindex(self.proj, self.env, "--no-pull")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        path = cache_file(self.proj)
        with open(path, "rb") as fh:
            pending = fh.read()
        again = run_reindex(self.proj, self.env, "--no-pull")
        self.assertEqual(again.returncode, 0, again.stderr)
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), pending)
        indexed = pending.replace(b"status: needs-extraction", b"status: indexed", 1)
        with open(path, "wb") as fh:
            fh.write(indexed)
        third = run_reindex(self.proj, self.env, "--no-pull")
        self.assertEqual(third.returncode, 0, third.stderr)
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), indexed)

    def test_local_pull_updates_full_sha_without_network(self):
        src = os.path.join(self.tmp.name, "src")
        os.makedirs(src)
        git(self.env, src, "init")
        with open(os.path.join(src, "f.txt"), "w", encoding="utf-8") as fh:
            fh.write("v1\n")
        git(self.env, src, "add", "f.txt")
        git(self.env, src, "commit", "-m", "init")
        clone = os.path.join(self.proj, "refs", "upstream")
        # demo already exists; point the config at a clone instead.
        git(self.env, self.proj, "clone", src, clone)
        cfg = os.path.join(self.proj, ".claude", "contextkit", "contextkit.config.json")
        with open(cfg, "w", encoding="utf-8") as fh:
            json.dump({
                "references": {"path": "refs", "repos": ["upstream"]},
                "knowledge": {"path": "knowledge"},
            }, fh)
        first = run_reindex(self.proj, self.env, "--no-pull")
        self.assertEqual(first.returncode, 0, first.stderr)
        path = os.path.join(
            self.proj, ".claude", "contextkit", "cache", "references", "upstream.md",
        )
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        text = text.replace("status: needs-extraction", "status: indexed", 1)
        text += "LIVE-FINDING-99\n"
        body = split_body(text)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        with open(os.path.join(src, "f.txt"), "a", encoding="utf-8") as fh:
            fh.write("v2\n")
        git(self.env, src, "add", "f.txt")
        git(self.env, src, "commit", "-m", "next")
        full = git(self.env, src, "rev-parse", "HEAD")
        pulled = run_reindex(self.proj, self.env)
        self.assertEqual(pulled.returncode, 0, pulled.stderr)
        with open(path, encoding="utf-8") as fh:
            updated = fh.read()
        self.assertEqual(git(self.env, clone, "rev-parse", "HEAD"), full)
        self.assertEqual(fm_value(updated, "sha"), full)
        self.assertEqual(fm_value(updated, "status"), "needs-extraction")
        self.assertEqual(split_body(updated), body)

    def test_stub_sections_follow_index_scope_and_platform(self):
        cfg = os.path.join(self.proj, ".claude", "contextkit", "contextkit.config.json")
        with open(cfg, "w", encoding="utf-8") as fh:
            json.dump({
                "platform": "android",
                "references": {"path": "refs", "repos": ["demo"]},
                "knowledge": {"path": "knowledge"},
                "indexScope": ["parity", "contracts", "custom-thing"],
            }, fh)
        proc = run_reindex(self.proj, self.env, "--no-pull")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(cache_file(self.proj), encoding="utf-8") as fh:
            text = fh.read()
        parity = text.index("## Parity (android <-> demo)")
        contracts = text.index("## Contracts / Public API")
        custom = text.index("## Custom Thing")
        self.assertLess(parity, contracts)
        self.assertLess(contracts, custom)
        self.assertNotIn("## API-Specs / Endpoints", text)
        self.assertNotIn("iOS", text)

    def test_default_config_stub_uses_generic_platform(self):
        proc = run_reindex(self.proj, self.env, "--no-pull")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(cache_file(self.proj), encoding="utf-8") as fh:
            text = fh.read()
        contracts = text.index("## Contracts / Public API")
        api = text.index("## API-Specs / Endpoints")
        parity = text.index("## Parity (generic <-> demo)")
        self.assertLess(contracts, api)
        self.assertLess(api, parity)


if __name__ == "__main__":
    unittest.main()
