#!/usr/bin/env python3
"""ContextKit doctor (V2) — checks the project-rooted setup.

Usage:  python3 .claude/contextkit/scripts/doctor.py
Exit 0 = ok (warnings allowed), exit 1 = at least one error.

The knowledge INDEX is read via the machine-readable anchor
`<!-- contextkit:entries=N -->`. An INDEX without that anchor is reported
as outdated so it can be regenerated. Xcode checks run only when
platform is ios.
"""
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contextkit_config as ck

OK, WARN, FAIL = "✅", "⚠️", "❌"
INDEX_ANCHOR = re.compile(r"<!-- contextkit:entries=(\d+) -->")


def parse_index_entries(text):
    """Return N from `<!-- contextkit:entries=N -->`, or None when it is absent.

    Prose in the header is ignored. Callers treat None as "regenerate".
    """
    match = INDEX_ANCHOR.search(text or "")
    if not match:
        return None
    return int(match.group(1))


def xcode_project_present(root):
    """True when root contains a .xcodeproj or .xcworkspace directory."""
    try:
        names = os.listdir(root)
    except OSError:
        return False
    for name in names:
        if name.endswith(".xcodeproj") or name.endswith(".xcworkspace"):
            if os.path.isdir(os.path.join(root, name)):
                return True
    return False


def run_checks(cfg):
    results = []

    def check(sym, title, detail=""):
        results.append((sym, title, detail))

    # 1 — Runtime
    check(OK if shutil.which("git") else FAIL, "Git available",
          "" if shutil.which("git") else "Install Git")
    if cfg["isHub"]:
        check(OK, "Mode", "HUB (.hub marker present)")
    if " " in cfg["root"]:
        check(WARN, "Project path contains spaces", "Always quote shell commands")

    # 2 — Config
    if os.path.exists(cfg["configPath"]):
        try:
            with open(cfg["configPath"], encoding="utf-8") as f:
                json.load(f)
            check(OK, "contextkit.config.json", "found, valid JSON")
        except ValueError as e:
            check(FAIL, "contextkit.config.json invalid", str(e))
    else:
        check(WARN, "contextkit.config.json missing", "Run /ck-setup — defaults are active")
    try:
        re.compile(cfg["ticketPattern"])
        check(OK, "ticketPattern compiles", cfg["ticketPattern"])
    except re.error as e:
        check(FAIL, "ticketPattern invalid", str(e))

    platform = cfg.get("platform") or "generic"
    if platform not in ck.KNOWN_PLATFORMS:
        check(WARN, "platform",
              "%s is not a known platform (generic, ios, android, web)" % platform)
    else:
        check(OK, "platform", platform)

    # Xcode is an ios-only check. Other platforms skip it entirely.
    if platform == "ios":
        if xcode_project_present(cfg["root"]):
            check(OK, "Xcode project", ".xcodeproj or .xcworkspace found")
        else:
            check(FAIL, "Xcode project",
                  "no .xcodeproj or .xcworkspace directory in the project root")

    # 3 — References
    rp = cfg["referencesPath"]
    check(OK if os.path.isdir(rp) else WARN, "Reference folder",
          rp if os.path.isdir(rp) else "%s is missing" % rp)
    if not cfg["references"]["repos"]:
        check(WARN, "No reference repos configured", "Run /ck-setup")
    for repo in cfg["references"]["repos"]:
        p = os.path.join(rp, repo)
        if not os.path.isdir(p):
            check(FAIL, "Reference '%s' not found" % repo, p)
        elif not os.path.exists(os.path.join(p, ".git")):
            check(WARN, "'%s' is not a git repo" % repo, "git pull / SHA tracking inactive")
        else:
            check(OK, "Reference '%s'" % repo, "git present")

    # 4 — Knowledge
    kp = cfg["knowledgePath"]
    if not os.path.isdir(kp):
        check(WARN, "Knowledge folder missing", "%s — /ck-setup can create it" % kp)
    else:
        check(OK, "Knowledge folder", kp)
        if not os.path.exists(os.path.join(kp, ".git")):
            check(WARN, "Knowledge folder is not a git repo", "Changes are not versioned")
        ignored = ck.knowledge_ignored(cfg)
        n = len([
            f for f in os.listdir(kp)
            if f.endswith(".md") and f not in ignored
        ])
        idx_path = os.path.join(kp, "INDEX.md")
        if not os.path.exists(idx_path):
            check(WARN if n else OK, "Knowledge INDEX.md",
                  "/ck-doctor builds it" if n else "still empty — fill it via /ck-create-note")
        else:
            with open(idx_path, encoding="utf-8") as f:
                text = f.read()
            idx_n = parse_index_entries(text)
            if idx_n is None:
                check(WARN, "Knowledge INDEX.md outdated", "regenerate")
            elif idx_n != n:
                check(WARN, "Knowledge INDEX.md outdated",
                      "index says %s entries, folder has %s — rebuild with knowledge.py"
                      % (idx_n, n))
            else:
                check(OK, "Knowledge INDEX.md", "%s entries" % n)

    # 5 — Tooling (install.py is hub-only and intentionally absent from a project)
    scripts_dir = os.path.join(cfg["contextkitHome"], "scripts")
    expected = {"contextkit_config.py", "setup.py", "reindex.py", "knowledge.py",
                "session-start.py", "doctor.py"}
    present = set(os.listdir(scripts_dir)) if os.path.isdir(scripts_dir) else set()
    missing = expected - present
    check(OK if not missing else FAIL, "contextkit/scripts/",
          "%s scripts present" % len(expected) if not missing
          else "missing: %s" % ", ".join(sorted(missing)))
    check(OK if os.path.isdir(cfg["cachePath"]) else WARN, "contextkit/cache/references",
          cfg["cachePath"] if os.path.isdir(cfg["cachePath"])
          else "created on the first reindex")
    return results


def main():
    cfg = ck.load()
    results = run_checks(cfg)
    print("# ContextKit Doctor (V2) — %s\n" % cfg["root"])
    fails = sum(1 for sym, _title, _detail in results if sym == FAIL)
    warns = sum(1 for sym, _title, _detail in results if sym == WARN)
    for sym, title, detail in results:
        print("%s %s" % (sym, title) + (" — %s" % detail if detail else ""))
    print("\n%s checks · %s errors · %s warnings" % (len(results), fails, warns))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
