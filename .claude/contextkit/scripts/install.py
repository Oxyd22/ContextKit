#!/usr/bin/env python3
"""ContextKit installer/updater (V2) — merge-safe, fully local.

Adds ONLY new, untracked files and never touches what is already there,
except its own ContextKit block and its own SessionStart hook:
  • <target>/.claude/contextkit/      namespace (scripts, config, cache, VERSION)
  • Skills (copies, never symlinks) — either:
      local  (default): <target>/.claude/skills/<name>/   + git exclude
      global (--skills-global): ~/.claude/skills/<name>/   (private, every project)
    Collision → skip and warn (never overwritten).
  • SessionStart hook merged into    <target>/.claude/settings.local.json (local)
  • <target>/CLAUDE.local.md          local context between marker comments
  • Lines in .git/info/exclude         everything new in the project stays invisible to git

Fresh:  python3 install.py /path/to/project [--skills-global | --skills-local]
Update: python3 install.py /path/to/project --update [--force]
        (refreshes scripts/ + owned skills + VERSION + hook + ContextKit block;
         config and cache are kept; skill location comes from .installed.json
         unless a flag overrides it)

Ownership: every skill directory this installer writes gets a
`.contextkit-owned` marker containing the ContextKit version. --update
overwrites or removes a skill directory only when that marker is present,
or when the name is listed in `.installed.json` for that same scope
(legacy installs: adopt by writing the marker). A name skipped at install
time because the directory already existed is not in the manifest and is
left untouched. tests/ and REVIEW* files are never copied.

Global skills: `--skills-global` keeps ~/.claude/skills/.contextkit.json
{"version": ...}. If the hub version is numerically older than the recorded
one, the command exits non-zero unless --force is set.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))         # hub/.claude/contextkit/scripts
HUB_CK = os.path.dirname(HERE)                            # hub/.claude/contextkit
HUB_CLAUDE = os.path.dirname(HUB_CK)                      # hub/.claude
HUB_SKILLS = os.path.join(HUB_CLAUDE, "skills")
HUB_ROOT = os.path.dirname(HUB_CLAUDE)

# Skills that belong in a project (migrate stays hub-only)
PROJECT_SKILLS = ["ck-setup", "ck-refs-lookup", "ck-refs-sync", "ck-create-note", "ck-read-note", "ck-doctor"]

HOOK_CMD = 'python3 "$CLAUDE_PROJECT_DIR/.claude/contextkit/scripts/session-start.py"'
# install.py is hub-only (like the migrate skill) — useless in a project, so never copied.
# tests/ and REVIEW files live outside .claude today; ignore them anyway so a
# future layout cannot leak them into a target project.
# CHANGELOG.md lives at the hub root and is never part of an install tree.
# Listed here so a future layout cannot copy it into a target either.
_JUNK = ("*.pyc", "__pycache__", ".DS_Store", "tests", "REVIEW*", "CHANGELOG.md")
NS_IGNORE = shutil.ignore_patterns("cache", ".hub", "install.py", *_JUNK)
SCRIPT_IGNORE = shutil.ignore_patterns("install.py", *_JUNK)
SKILL_IGNORE = shutil.ignore_patterns(*_JUNK)

OWNED_MARKER = ".contextkit-owned"
GLOBAL_VERSION_FILE = ".contextkit.json"

# Marker comments delimit the block --update is allowed to refresh.
# A CLAUDE.local.md that has neither marker is left untouched.
CLAUDE_LOCAL_BEGIN = "<!-- contextkit:begin -->"
CLAUDE_LOCAL_END = "<!-- contextkit:end -->"

CLAUDE_LOCAL = """# ContextKit (local)

> This project uses **ContextKit** (local, not in the team repo).
> Tooling: `.claude/contextkit/` · Skills: `/ck-read-note`, `/ck-create-note`, `/ck-refs-lookup`,
> `/ck-refs-sync`, `/ck-doctor`, `/ck-setup` (reconfigure).

- **Second brain** (read/write): `/ck-read-note <question>` looks up knowledge and decisions
  (index first), `/ck-create-note <...>` records something new, `/ck-doctor` keeps it consistent.
- **References** (read-only): `/ck-refs-lookup <topic>`, index via `/ck-refs-sync`.
- Before a decision, run `/ck-read-note` — is there already one (possibly superseded)?
- Paths live in `.claude/contextkit/contextkit.config.json`.
"""


def read_version(ck_dir):
    try:
        with open(os.path.join(ck_dir, "VERSION")) as f:
            return f.read().strip()
    except OSError:
        return "?"


def version_tuple(value):
    """Parse a dotted version into a tuple of ints for numeric comparison.

    Non-numeric tails inside a component are ignored ("2.2.0-rc1" → (2, 2, 0)).
    Returns an empty tuple when nothing numeric was found.
    """
    parts = []
    for piece in str(value).strip().split("."):
        digits = []
        for ch in piece.strip():
            if ch.isdigit():
                digits.append(ch)
            else:
                break
        if not digits:
            break
        parts.append(int("".join(digits)))
    return tuple(parts)


def version_is_older(left, right):
    """True when left is a numerically older version than right.

    Missing numeric components compare as 0, so 2.2 == 2.2.0.
    """
    a = version_tuple(left)
    b = version_tuple(right)
    if not a or not b:
        return False
    width = max(len(a), len(b))
    a = a + (0,) * (width - len(a))
    b = b + (0,) * (width - len(b))
    return a < b


def global_skills_root():
    return os.path.join(os.path.expanduser("~"), ".claude", "skills")


def global_version_path():
    return os.path.join(global_skills_root(), GLOBAL_VERSION_FILE)


def read_global_version():
    """Return the recorded global skills version string, or None."""
    try:
        with open(global_version_path(), encoding="utf-8") as f:
            loaded = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(loaded, dict):
        return None
    version = loaded.get("version")
    if version is None:
        return None
    return str(version)


def write_global_version(version):
    path = global_version_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {}
    try:
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            data = loaded
    except (OSError, ValueError):
        data = {}
    data["version"] = version
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def ensure_global_downgrade_allowed(force):
    """Exit non-zero when the hub is older than the recorded global skills.

    Must run before any install writes. --force continues and the caller
    records the hub version only after it actually copies skills.
    """
    recorded = read_global_version()
    if not recorded:
        return
    hub = read_version(HUB_CK)
    if not version_is_older(hub, recorded):
        return
    if force:
        print("⚠️  Global skills downgrade %s → %s allowed by --force" % (recorded, hub))
        return
    print("❌ Refusing to downgrade global ContextKit skills from %s to %s. "
          "Pass --force to override." % (recorded, hub))
    sys.exit(1)


def skills_dir(target, scope):
    """Destination skill folder for this install location (copies, never symlinks)."""
    if scope == "global":
        return global_skills_root()
    return os.path.join(target, ".claude", "skills")


def owned_marker_path(skill_dir):
    return os.path.join(skill_dir, OWNED_MARKER)


def has_owner_marker(skill_dir):
    return os.path.isfile(owned_marker_path(skill_dir))


def write_owner_marker(skill_dir):
    version = read_version(HUB_CK)
    with open(owned_marker_path(skill_dir), "w", encoding="utf-8") as f:
        f.write(version + "\n")


def may_modify_skill(skill_dir, name, adopt_names):
    """True when update may overwrite or remove this skill directory.

    adopt_names is the manifest skill list for this directory's scope only.
    A collision skipped at install time is absent from that list and has no
    marker, so it stays untouched.
    """
    if not os.path.isdir(skill_dir):
        return False
    if has_owner_marker(skill_dir):
        return True
    return name in adopt_names


def copy_skill(name, dst_skills, overwrite, adopt_names=None):
    """Copy one skill. Return its name when this call wrote the directory.

    overwrite=False (fresh install): an existing directory is a collision and
    is never replaced. overwrite=True (--update): replace the directory only
    when it carries the owner marker or its name is in adopt_names (legacy
    manifest entry for this scope). The copy always receives a marker.
    """
    if adopt_names is None:
        adopt_names = ()
    src = os.path.join(HUB_SKILLS, name)
    dst = os.path.join(dst_skills, name)
    if not os.path.isdir(src):
        return None
    if os.path.isdir(dst):
        if not (overwrite and may_modify_skill(dst, name, adopt_names)):
            if overwrite:
                print("⏭️  Skill '%s' is not owned by ContextKit — left untouched" % name)
            else:
                print("⏭️  Skill '%s' already exists — skipped (not overwritten)" % name)
            return None
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=SKILL_IGNORE)
    write_owner_marker(dst)
    return name


def remove_skill_if_allowed(dst_skills, name, adopt_names):
    """Remove a skill directory when this scope owns it. Return True if removed."""
    dst = os.path.join(dst_skills, name)
    if not os.path.isdir(dst):
        return False
    if not may_modify_skill(dst, name, adopt_names):
        print("⏭️  Skill '%s' is not owned by ContextKit — left untouched" % name)
        return False
    shutil.rmtree(dst)
    return True


def prune_empty_local_skills(target):
    """Drop <target>/.claude/skills when a scope switch left it empty."""
    path = os.path.join(target, ".claude", "skills")
    try:
        if os.path.isdir(path) and not os.listdir(path):
            os.rmdir(path)
    except OSError:
        pass


def is_hub_path(target):
    """True when target is the hub itself or a directory inside it.

    realpath resolves symlinks; commonpath treats the hub and any descendant
    as the same tree, including paths reached through a link.
    """
    target_real = os.path.realpath(target)
    hub_real = os.path.realpath(HUB_ROOT)
    try:
        return os.path.commonpath([target_real, hub_real]) == hub_real
    except ValueError:
        return False


def merge_hook(target):
    path = os.path.join(target, ".claude", "settings.local.json")
    data = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except ValueError:
            print("⚠️  settings.local.json is not valid JSON — hook NOT merged.")
            return
    sessionstart = data.setdefault("hooks", {}).setdefault("SessionStart", [])
    for group in sessionstart:
        for h in group.get("hooks", []):
            if "contextkit/scripts/session-start.py" in h.get("command", ""):
                if "async" in h:
                    # Async hooks never inject their stdout into the session — repair old installs.
                    del h["async"]
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                        f.write("\n")
                    print("✅ SessionStart hook repaired (removed async)")
                else:
                    print("✅ SessionStart hook already present in settings.local.json")
                return
    sessionstart.append({"hooks": [{"type": "command", "command": HOOK_CMD}]})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print("✅ SessionStart hook merged into settings.local.json")


def render_claude_local():
    body = CLAUDE_LOCAL
    if not body.endswith("\n"):
        body += "\n"
    return CLAUDE_LOCAL_BEGIN + "\n" + body + CLAUDE_LOCAL_END + "\n"


def write_claude_local(target, refresh=False):
    """Write CLAUDE.local.md, or refresh only the marked ContextKit block.

    Fresh installs write the begin/end markers. On update, a file that already
    has both markers gets the block replaced and text outside the markers is
    kept. A file with no markers (installs from before markers existed) is
    left untouched.
    """
    path = os.path.join(target, "CLAUDE.local.md")
    block = render_claude_local()
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(block)
        print("✅ CLAUDE.local.md created")
        return
    if not refresh:
        print("⏭️  CLAUDE.local.md already exists — not overwritten")
        return
    with open(path, encoding="utf-8") as f:
        text = f.read()
    begin = text.find(CLAUDE_LOCAL_BEGIN)
    end = text.find(CLAUDE_LOCAL_END)
    if begin == -1 or end == -1 or end < begin:
        print("⏭️  CLAUDE.local.md has no ContextKit markers — left untouched")
        return
    end_after = end + len(CLAUDE_LOCAL_END)
    rest = text[end_after:]
    # The canonical block already ends in a newline; don't duplicate the one
    # that used to follow the old end marker.
    if rest.startswith("\n") and block.endswith("\n"):
        rest = rest[1:]
    new_text = text[:begin] + block + rest
    if new_text != text:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_text)
        print("✅ CLAUDE.local.md ContextKit block refreshed")
    else:
        print("✅ CLAUDE.local.md ContextKit block already current")


def set_excludes(target, skills, scope):
    # git-common-dir rather than .git itself: in a worktree .git is a FILE
    # (gitdir: ...), not a directory. --git-common-dir resolves the shared
    # main .git, including the worktree case.
    r = subprocess.run(["git", "-C", target, "rev-parse", "--git-common-dir"],
                        capture_output=True, text=True)
    if r.returncode != 0:
        print("⚠️  No .git in the target — skipped excludes. Ignore the new files yourself.")
        return
    common_dir = r.stdout.strip()
    if not os.path.isabs(common_dir):
        common_dir = os.path.normpath(os.path.join(target, common_dir))
    exclude = os.path.join(common_dir, "info", "exclude")
    os.makedirs(os.path.dirname(exclude), exist_ok=True)
    entries = ["/.claude/contextkit/", "/CLAUDE.local.md", "/.claude/settings.local.json"]
    # Global skills live outside the project (~/.claude/) — no exclude entry needed.
    if scope == "local":
        entries += [f"/.claude/skills/{s}/" for s in skills]
    lines = []
    if os.path.exists(exclude):
        with open(exclude, encoding="utf-8") as f:
            lines = f.read().splitlines()
    added = [e for e in entries if e not in lines]
    if added:
        lines += added
        with open(exclude, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print(f"✅ {len(added)} entries in .git/info/exclude (hidden from git)")
    else:
        print("✅ Exclude entries already present")


def write_manifest(target, skills, scope):
    manifest = {"version": read_version(HUB_CK), "skills": skills, "skillsScope": scope}
    with open(os.path.join(target, ".claude", "contextkit", ".installed.json"),
              "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")


def read_manifest(target):
    try:
        with open(os.path.join(target, ".claude", "contextkit", ".installed.json")) as f:
            man = json.load(f)
    except (OSError, ValueError):
        return {"version": "?", "skills": PROJECT_SKILLS, "skillsScope": "local"}
    man.setdefault("skillsScope", "local")  # older manifests: local
    skills = man.get("skills", [])
    if not isinstance(skills, list):
        skills = list(PROJECT_SKILLS)
    man["skills"] = skills
    return man


def manifest_names_for_scope(man, scope):
    """Skill names the manifest authorizes us to touch in `scope`.

    Names belong to the scope recorded in the manifest. They must not be used
    to overwrite a same-named directory in the other scope.
    """
    if man.get("skillsScope", "local") != scope:
        return []
    return list(man.get("skills", []))


def hub_skill_names():
    try:
        return set(os.listdir(HUB_SKILLS))
    except OSError:
        return set()


def fresh_install(target, scope, force=False):
    dst_ck = os.path.join(target, ".claude", "contextkit")
    if os.path.exists(dst_ck):
        print(f"⚠️  {dst_ck} already exists — for an update, pass --update.")
        sys.exit(1)
    if scope == "global":
        ensure_global_downgrade_allowed(force)
    # Parent of the namespace must exist. The local skills dir is created only
    # for scope "local" — a global install must not leave an empty
    # <target>/.claude/skills behind.
    os.makedirs(os.path.join(target, ".claude"), exist_ok=True)
    if scope == "local":
        os.makedirs(os.path.join(target, ".claude", "skills"), exist_ok=True)
    shutil.copytree(HUB_CK, dst_ck, ignore=NS_IGNORE)
    os.makedirs(os.path.join(dst_ck, "cache", "references"), exist_ok=True)
    print(f"✅ Namespace installed: {dst_ck}  (ContextKit {read_version(HUB_CK)})")

    dst_skills = skills_dir(target, scope)
    os.makedirs(dst_skills, exist_ok=True)
    installed = []
    for name in PROJECT_SKILLS:
        copied = copy_skill(name, dst_skills, overwrite=False)
        if copied:
            installed.append(copied)
    loc = "global (~/.claude/skills)" if scope == "global" else "local (.claude/skills)"
    print(f"✅ Skills installed [{loc}]: {', '.join(installed) if installed else '(none new)'}")
    if scope == "global" and installed:
        write_global_version(read_version(HUB_CK))

    merge_hook(target)
    write_claude_local(target)
    write_manifest(target, installed, scope)
    set_excludes(target, installed, scope)
    print("\nNext step — in the project, from a Claude session: /ck-setup")


def update(target, scope=None, force=False):
    dst_ck = os.path.join(target, ".claude", "contextkit")
    if not os.path.isdir(dst_ck):
        print(f"❌ {dst_ck} is missing — install fresh first (without --update).")
        sys.exit(1)
    man = read_manifest(target)
    old_scope = man.get("skillsScope", "local")
    scope = scope or old_scope
    if scope == "global":
        ensure_global_downgrade_allowed(force)
    old = read_version(dst_ck)

    # Refresh scripts/ only — config and cache stay.
    d_scripts = os.path.join(dst_ck, "scripts")
    if os.path.isdir(d_scripts):
        shutil.rmtree(d_scripts)
    shutil.copytree(os.path.join(HUB_CK, "scripts"), d_scripts, ignore=SCRIPT_IGNORE)
    shutil.copy2(os.path.join(HUB_CK, "VERSION"), os.path.join(dst_ck, "VERSION"))

    # Switching local → global (or local → an explicit other scope) drops the
    # project-private copies we installed. Global skills are shared across
    # projects, so a single project switching away from global must not delete
    # them. Names authorize a delete only in the scope that recorded them,
    # plus any directory that already carries the owner marker.
    if scope != old_scope and old_scope == "local":
        adopt_old = manifest_names_for_scope(man, old_scope)
        old_dir = skills_dir(target, old_scope)
        names = list(dict.fromkeys(list(man.get("skills", [])) + PROJECT_SKILLS))
        for name in names:
            if remove_skill_if_allowed(old_dir, name, adopt_old):
                print("🗑️  ContextKit skill removed from the previous local scope: %s" % name)
        prune_empty_local_skills(target)

    # Owned skills are refreshed; skills ContextKit did not install stay put.
    # Manifest names apply only when the update scope is the recorded scope
    # (legacy installs without a marker are adopted by the rewrite below).
    dst_skills = skills_dir(target, scope)
    os.makedirs(dst_skills, exist_ok=True)
    adopt = manifest_names_for_scope(man, scope)
    known_in_hub = hub_skill_names()
    extras = [s for s in man.get("skills", []) if s in known_in_hub]
    want = list(dict.fromkeys(list(PROJECT_SKILLS) + extras))
    refreshed = []
    for name in want:
        copied = copy_skill(name, dst_skills, overwrite=True, adopt_names=adopt)
        if copied:
            refreshed.append(copied)

    # Skills we previously installed that this hub no longer ships.
    obsolete = [s for s in man.get("skills", [])
                if s not in PROJECT_SKILLS and s not in known_in_hub]
    # Same shared-global rule as above: do not delete global skills while this
    # project is moving them out of the global scope.
    if obsolete and not (old_scope == "global" and scope != "global"):
        obsolete_dir = skills_dir(target, old_scope)
        adopt_obsolete = manifest_names_for_scope(man, old_scope)
        for name in obsolete:
            if remove_skill_if_allowed(obsolete_dir, name, adopt_obsolete):
                print("🗑️  Removed obsolete ContextKit skill: %s" % name)
        if old_scope == "local":
            prune_empty_local_skills(target)

    if scope == "global" and refreshed:
        write_global_version(read_version(HUB_CK))

    merge_hook(target)
    write_claude_local(target, refresh=True)
    write_manifest(target, refreshed, scope)
    set_excludes(target, refreshed, scope)

    new = read_version(HUB_CK)
    loc = "global (~/.claude/skills)" if scope == "global" else "local (.claude/skills)"
    print(f"✅ Updated: {dst_ck}")
    print(f"   Version {old} → {new}")
    print(f"   Skills refreshed [{loc}]: {', '.join(refreshed) if refreshed else '(none)'}")
    print("   Kept: contextkit.config.json, cache/, skills ContextKit does not own")
    print("\nNext step — in the project: python3 .claude/contextkit/scripts/doctor.py")


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="install.py",
        description="Install or update ContextKit in a project directory.",
    )
    ap.add_argument("target", help="Path to the project directory")
    ap.add_argument("--update", action="store_true",
                    help="Refresh scripts, VERSION, owned skills, the SessionStart hook, "
                         "and the ContextKit block in CLAUDE.local.md")
    scope_flags = ap.add_mutually_exclusive_group()
    scope_flags.add_argument("--skills-global", action="store_true",
                             help="Copy skills into ~/.claude/skills (shared per user)")
    scope_flags.add_argument("--skills-local", action="store_true",
                             help="Copy skills into <target>/.claude/skills (default)")
    ap.add_argument("--force", action="store_true",
                    help="Allow a global skills install older than ~/.claude/skills/.contextkit.json")
    args = ap.parse_args(argv)

    target = os.path.abspath(args.target)
    if not os.path.isdir(target):
        print(f"❌ Target directory does not exist: {target}")
        sys.exit(1)
    if is_hub_path(target):
        print("❌ Target is the ContextKit hub or inside it. Pass the project directory.")
        sys.exit(1)

    scope = None
    if args.skills_global:
        scope = "global"
    elif args.skills_local:
        scope = "local"

    if args.update:
        update(target, scope, force=args.force)
    else:
        fresh_install(target, scope or "local", force=args.force)


if __name__ == "__main__":
    main()
