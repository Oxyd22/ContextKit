#!/usr/bin/env python3
"""ContextKit reindex (V2) — git pull across references, plus an index skeleton.

1. For each reference repo: git pull --ff-only (dirty or diverged → warn, skip).
2. SHA diff against the last index — unchanged repos are skipped.
3. For changed repos: write an index STUB to contextkit/cache/references/<repo>.md
   with provenance frontmatter and extraction markers.

Stub section headings come from config `indexScope`. The three default names
keep their headings: contracts, api-specs, and parity. The parity heading is
`Parity ({platform} <-> {repo})`.

Semantic extraction (contracts / API / parity) is done by Claude via the
/ck-refs-sync skill — this script only orchestrates (pull, SHA diff, skeleton).

Flags:  --no-pull   check the index state only, no git pull
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contextkit_config as ck

NO_PULL = "--no-pull" in sys.argv
CFG = ck.load()
# git pull must not wait on a credential prompt.
PULL_TIMEOUT = 120

# Default scope names keep these headings. Any other scope becomes a title.
_SCOPE_TITLES = {
    "contracts": "Contracts / Public API",
    "api-specs": "API-Specs / Endpoints",
    "parity": "Parity ({platform} <-> {repo})",
}
_SCOPE_HINTS = {
    "contracts": "Contracts / public API surface (interfaces, public types, DTOs)",
    "api-specs": "API specs / endpoints / routing",
    "parity": "Parity ({platform} <-> {repo}): counterparts and divergences",
}


def git(repo, *args, timeout=None):
    """Run git in `repo`. GIT_TERMINAL_PROMPT=0 so a missing credential fails fast."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    cmd = ["git", "-C", repo, *args]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", "timeout")


def pull(repo):
    return git(repo, "pull", "--ff-only", timeout=PULL_TIMEOUT)


def head_sha(repo):
    """Full commit SHA (not --short; short SHAs grow and look like changes)."""
    r = git(repo, "rev-parse", "HEAD")
    return r.stdout.strip() if r.returncode == 0 else None


def _short(sha):
    """Display form only. The cache always stores the full SHA."""
    if not sha:
        return "?"
    return sha[:12]


def is_dirty(repo):
    return bool(git(repo, "status", "--porcelain").stdout.strip())


def _frontmatter_body(text):
    """Return (frontmatter_inner, body) or (None, text) when there is no frontmatter."""
    m = re.match(r"\A---\r?\n(.*?)\r?\n---[ \t]*\r?\n?", text, re.DOTALL)
    if not m:
        return None, text
    return m.group(1), text[m.end():]


def cached_value(cache_file, key):
    """Read one frontmatter scalar. Ignores the same key if it appears in the body."""
    if not os.path.exists(cache_file):
        return None
    with open(cache_file, encoding="utf-8") as f:
        text = f.read()
    fm, _body = _frontmatter_body(text)
    if fm is None:
        return None
    pat = re.compile(r"^" + re.escape(key) + r":\s*(\S+)")
    for line in fm.splitlines():
        m = pat.match(line.strip())
        if m:
            return m.group(1)
    return None


def _set_fm_key(fm, key, value):
    pat = re.compile(r"^" + re.escape(key) + r":\s*")
    out = []
    found = False
    for line in fm.splitlines():
        if pat.match(line):
            out.append("%s: %s" % (key, value))
            found = True
        else:
            out.append(line)
    if not found:
        out.append("%s: %s" % (key, value))
    return "\n".join(out)


def update_frontmatter(text, sha):
    """Set sha + status: needs-extraction and keep every byte of the body."""
    fm, body = _frontmatter_body(text)
    if fm is None:
        fm = ""
        body = text
    fm = _set_fm_key(fm, "sha", sha)
    fm = _set_fm_key(fm, "status", "needs-extraction")
    return "---\n%s\n---\n%s" % (fm, body)


def index_scopes(cfg):
    """Scope names that become stub sections, in config order."""
    raw = cfg.get("indexScope")
    if not isinstance(raw, list):
        raw = ck.DEFAULTS["indexScope"]
    return [str(item) for item in raw]


def _fill(template, platform, repo):
    return template.replace("{platform}", platform).replace("{repo}", repo)


def scope_heading(scope, platform, repo):
    """Heading for one indexScope name. The three defaults keep fixed titles."""
    title = _SCOPE_TITLES.get(scope)
    if title is None:
        title = str(scope).replace("-", " ").replace("_", " ").strip().title() or "Scope"
    return "## " + _fill(title, platform, repo)


def scope_hint(scope, platform, repo):
    hint = _SCOPE_HINTS.get(scope)
    if hint is None:
        hint = str(scope)
    return "- " + _fill(hint, platform, repo)


def render_stub(repo, sha, path, scopes, platform):
    """Index skeleton. Sections follow `scopes`; parity is labeled with `platform`."""
    hints = "\n".join(scope_hint(scope, platform, repo) for scope in scopes)
    if not hints:
        hints = "- (no indexScope configured)"
    sections = "\n\n".join(scope_heading(scope, platform, repo) for scope in scopes)
    body = (
        "<!-- CONTEXTKIT:EXTRACT\n"
        "Claude: read the reference repo at\n"
        "  %s\n"
        "and fill ONLY the sections below with:\n"
        "%s\n"
        "Keep it terse. Link, do not copy. No implementation detail.\n"
        "Then set `status: indexed` and `indexed: <today's date>` in the frontmatter.\n"
        "-->\n" % (path, hints)
    )
    if sections:
        body += "\n" + sections + "\n"
    return (
        "---\n"
        "repo: %s\n"
        "sha: %s\n"
        "indexed: pending\n"
        "scope: %s\n"
        "status: needs-extraction\n"
        "---\n"
        "%s" % (repo, sha, ", ".join(scopes), body)
    )


def main():
    ck.abort_on_config_error(CFG)
    refs_path = CFG["referencesPath"]
    cache = CFG["cachePath"]
    os.makedirs(cache, exist_ok=True)
    repos = CFG["references"]["repos"]
    scopes = index_scopes(CFG)
    platform = CFG.get("platform") or "generic"

    print("# ContextKit Reindex\n")
    if not repos:
        print("No reference repos configured. Run /ck-setup first.")
        return

    changed = []
    for repo in repos:
        p = os.path.join(refs_path, repo)
        if not os.path.exists(os.path.join(p, ".git")):
            print("⚠️  %s: not a git repo (%s) — skipped" % (repo, p))
            continue

        before = head_sha(p)
        if NO_PULL:
            pass
        elif is_dirty(p):
            print("⚠️  %s: uncommitted changes — no pull" % repo)
        else:
            r = pull(p)
            if r.returncode != 0:
                tail = (r.stderr.strip().splitlines() or ["diverged?"])[-1]
                print("⚠️  %s: pull failed (%s) — keeping the previous revision" % (repo, tail))
        after = head_sha(p)

        cache_file = os.path.join(cache, "%s.md" % repo)
        prev = cached_value(cache_file, "sha")
        if after and after == prev and os.path.exists(cache_file):
            if cached_value(cache_file, "status") == "needs-extraction":
                print("⏳ %s: %s — extraction pending" % (repo, _short(after)))
                changed.append(repo)
            else:
                print("✅ %s: unchanged (%s) — index is current" % (repo, _short(after)))
            continue

        os.makedirs(os.path.dirname(cache_file), exist_ok=True)
        if os.path.exists(cache_file):
            # SHA moved: refresh provenance only. Live findings in the body stay.
            with open(cache_file, encoding="utf-8") as f:
                current = f.read()
            with open(cache_file, "w", encoding="utf-8") as f:
                f.write(update_frontmatter(current, after or "unknown"))
        else:
            with open(cache_file, "w", encoding="utf-8") as f:
                f.write(render_stub(repo, after or "unknown", p, scopes, platform))
        arrow = "%s → %s" % (_short(before), _short(after)) if before != after else (_short(after) or "?")
        print("♻️  %s: %s — index stub refreshed, needs extraction" % (repo, arrow))
        changed.append(repo)

    print()
    if changed:
        print("%s repo(s) need extraction: %s" % (len(changed), ", ".join(changed)))
        print("→ Run /ck-refs-sync so the stubs get filled.")
    else:
        print("All indexes are current.")


if __name__ == "__main__":
    main()
