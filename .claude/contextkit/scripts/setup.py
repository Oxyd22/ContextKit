#!/usr/bin/env python3
"""ContextKit setup (V2) — scanner and writer for the config.

The primary path is the **/ck-setup skill**: Claude asks the questions in the
session and calls this script only to scan and write (stdin prompts do not
work in an agent session).

Modes:
  --scan   --references-path REL [--platform VALUE]
           Print the git repos found under REL as JSON.
           --platform is accepted and validated; a scan does not write the config.

  --write  --references-path REL  --repos "a,b,c"  --knowledge-path REL
           [--ticket-pattern REGEX] [--platform VALUE] [--create-knowledge]
           Write contextkit/contextkit.config.json (relative paths).
           --platform must be a non-empty [a-z0-9_-]+ token. Omitted, the
           existing value is kept, or "generic" when the key is absent.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contextkit_config as ck


def find_git_repos(abs_path):
    if not os.path.isdir(abs_path):
        return []
    return sorted(d for d in os.listdir(abs_path)
                  if os.path.exists(os.path.join(abs_path, d, ".git")))


def checked_platform(raw):
    """Validate --platform. None means the flag was omitted.

    Exits 2 when the value is empty or outside [a-z0-9_-]+. Leading and
    trailing whitespace is stripped before the check; the stored token is
    the stripped value. Case is not folded here (load() folds on read).
    """
    if raw is None:
        return None
    token = raw.strip() if isinstance(raw, str) else ""
    if not ck.valid_platform_token(token):
        print("contextkit: invalid --platform (expected a non-empty value "
              "matching [a-z0-9_-]+)", file=sys.stderr)
        sys.exit(2)
    return token


def do_scan(ref_rel):
    abs_path = os.path.normpath(os.path.join(ck.PROJECT_ROOT, ref_rel))
    print(json.dumps({
        "referencesPath": abs_path,
        "exists": os.path.isdir(abs_path),
        "repos": find_git_repos(abs_path),
    }, ensure_ascii=False, indent=2))


def _init_knowledge_repo(know_abs):
    """git init the knowledge folder when git exists and it is not a repo yet."""
    if os.path.exists(os.path.join(know_abs, ".git")):
        return
    if not shutil.which("git"):
        print("contextkit: git not available — knowledge folder was not initialized",
              file=sys.stderr)
        return
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    r = subprocess.run(["git", "init"], cwd=know_abs, env=env,
                       capture_output=True, text=True)
    if r.returncode != 0:
        detail = (r.stderr or r.stdout or "git init failed").strip()
        print("contextkit: git init failed: %s" % detail, file=sys.stderr)
        sys.exit(r.returncode or 1)
    print("Initialized git repository in %s" % know_abs)


def do_write(args, platform):
    if args.ticket_pattern:
        try:
            re.compile(args.ticket_pattern)
        except re.error as e:
            print("contextkit: invalid --ticket-pattern: %s" % e, file=sys.stderr)
            sys.exit(2)
    # Read the existing config RAW (not ck.load() — that mixes in computed
    # fields) so project keys such as `schema` / `staleProposedDays` survive
    # a reconfigure.
    try:
        with open(ck.CONFIG_PATH, encoding="utf-8") as f:
            out = json.load(f)
        if not isinstance(out, dict):
            raise ValueError("top-level value must be a JSON object")
    except (OSError, ValueError):
        out = json.loads(json.dumps(ck.DEFAULTS))  # deep copy of the defaults
    repos = [r.strip() for r in (args.repos or "").split(",") if r.strip()]
    out["references"] = {"path": args.references_path, "repos": repos}
    out["knowledge"] = {"path": args.knowledge_path}
    if args.ticket_pattern:
        out["ticketPattern"] = args.ticket_pattern
    if platform is not None:
        out["platform"] = platform
    # Everything else (indexScope, schema, stale*, checkMaxAgeDays, ...) stays.
    for k in ("platform", "indexScope", "ticketPattern", "checkMaxAgeDays", "refreshMaxAgeDays"):
        out.setdefault(k, ck.DEFAULTS[k])
    with open(ck.CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print("✅ Wrote %s" % ck.CONFIG_PATH)
    print("   References: %s" % (", ".join(repos) if repos else "(none)"))

    know_abs = os.path.normpath(os.path.join(ck.PROJECT_ROOT, args.knowledge_path))
    if args.create_knowledge:
        if not os.path.isdir(know_abs):
            os.makedirs(know_abs, exist_ok=True)
            print("✅ Created %s" % know_abs)
        _init_knowledge_repo(know_abs)
    os.makedirs(ck.load()["cachePath"], exist_ok=True)


def main(argv=None):
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--references-path")
    ap.add_argument("--repos")
    ap.add_argument("--knowledge-path")
    ap.add_argument("--ticket-pattern")
    ap.add_argument("--platform",
                    help="Platform token [a-z0-9_-]+ (generic, ios, android, web, or a custom value)")
    ap.add_argument("--create-knowledge", action="store_true")
    a = ap.parse_args(argv)
    platform = checked_platform(a.platform)

    if a.scan:
        if not a.references_path:
            ap.error("--scan requires --references-path")
        do_scan(a.references_path)
    elif a.write:
        if not (a.references_path and a.knowledge_path):
            ap.error("--write requires --references-path and --knowledge-path")
        do_write(a, platform)
    else:
        ap.error("pass --scan or --write (the /ck-setup skill asks the questions)")


if __name__ == "__main__":
    main()
