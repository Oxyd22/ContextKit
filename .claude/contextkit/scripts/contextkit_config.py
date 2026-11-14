"""Shared configuration for every ContextKit script (blueprint V2).

Layout: ContextKit lives in the namespace <project>/.claude/contextkit/
so it does not collide with an existing .claude/ (other skills, settings).

Root resolution does not depend on the working directory:
  * CONTEXTKIT_HOME = parent of scripts/          (.../.claude/contextkit)
  * CLAUDE_DIR      = nearest `.claude` ancestor  (.../.claude)
  * PROJECT_ROOT    = parent of that directory    (the project)

The same resolution works in Claude Code and from any subdirectory.
Scripts locate themselves from their own file path. The SessionStart hook
(session-start.py) is Claude Code only; elsewhere, /ck-doctor shows the
same overview on demand.

`platform` defaults to "generic". Known values are generic, ios, android,
and web. Other values are kept. Xcode checks run only when the value is ios.

Python standard library only.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))      # .../.claude/contextkit/scripts
CONTEXTKIT_HOME = os.path.dirname(HERE)                 # .../.claude/contextkit

# Lower-case token written by setup.py --platform. Load normalizes case.
PLATFORM_TOKEN = re.compile(r"^[a-z0-9_-]+$")
KNOWN_PLATFORMS = ("generic", "ios", "android", "web")


def _find_claude_dir(start):
    d = start
    while True:
        if os.path.basename(d) == ".claude":
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


CLAUDE_DIR = _find_claude_dir(HERE) or os.path.dirname(CONTEXTKIT_HOME)
PROJECT_ROOT = os.path.dirname(CLAUDE_DIR)
CONFIG_PATH = os.path.join(CONTEXTKIT_HOME, "contextkit.config.json")
HUB_MARKER = os.path.join(CONTEXTKIT_HOME, ".hub")
VERSION_PATH = os.path.join(CONTEXTKIT_HOME, "VERSION")

DEFAULTS = {
    "platform": "generic",
    "references": {"path": "../references", "repos": []},
    # `ignore`: file names in the knowledge folder that are not knowledge entries
    # (INDEX.md and LOG.md are always ignored).
    "knowledge": {"path": "../project-knowledge", "ignore": ["README.md"]},
    "indexScope": ["contracts", "api-specs", "parity"],
    "ticketPattern": r"[A-Z][A-Z0-9]+-\d+",
    "checkMaxAgeDays": 7,
    "refreshMaxAgeDays": 14,
    # Schema is intentionally minimal. A project may extend it here (for example
    # person/workflow as first-class types). Only types listed in `status` carry
    # a status; every other type has none. Anything else is filed under
    # "Uncategorized" in the index.
    "schema": {
        "types": ["note", "decision", "ticket"],
        "status": {
            "decision": ["proposed", "accepted", "superseded"],
            "ticket": ["open", "done"],
        },
    },
    "staleProposedDays": 21,   # proposed decision open longer than this → lint warning
    "staleOpenTicketDays": 30,  # open ticket open longer than this → lint warning
}


def normalize_platform(value):
    """Return a lower-case platform string. Blank values become "generic"."""
    if value is None:
        return "generic"
    text = str(value).strip().lower()
    return text or "generic"


def valid_platform_token(value):
    """True when value is a non-empty [a-z0-9_-]+ token (no case folding)."""
    return isinstance(value, str) and PLATFORM_TOKEN.fullmatch(value) is not None


def _abspath(rel):
    return os.path.normpath(os.path.join(PROJECT_ROOT, rel))


def _merge(base, override):
    """Recursive merge. Nested dicts (for example schema.status) merge per key
    instead of being replaced on the first hit."""
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v


def knowledge_ignored(cfg):
    """File names in the knowledge folder that are never treated as entries."""
    extra = (cfg.get("knowledge") or {}).get("ignore") or []
    if isinstance(extra, str):
        extra = [extra]
    return {"INDEX.md", "LOG.md"} | {str(n) for n in extra}


def abort_on_config_error(cfg):
    """Exit(2) when the config file exists but is invalid.

    Scripts that WRITE (knowledge.py, reindex.py) call this so they never fall
    back to the default folders because of a broken config.
    """
    if cfg.get("configError"):
        print(f"contextkit: aborting, invalid config {cfg['configPath']} — fix it or "
              f"re-run /ck-setup.", file=sys.stderr)
        sys.exit(2)


def load():
    cfg = json.loads(json.dumps(DEFAULTS))  # deep copy
    config_error = None
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            user = json.load(f)
        if not isinstance(user, dict):
            raise ValueError("top-level value must be a JSON object")
        _merge(cfg, user)
    except OSError:
        pass  # missing config: defaults are fine
    except ValueError as e:
        # Invalid JSON must not be silently replaced by defaults.
        config_error = str(e)
        print(f"contextkit: warning: {CONFIG_PATH} is not valid JSON ({e}) — "
              f"using defaults.", file=sys.stderr)

    cfg["configError"] = config_error
    cfg["platform"] = normalize_platform(cfg.get("platform"))

    cfg["root"] = PROJECT_ROOT
    cfg["contextkitHome"] = CONTEXTKIT_HOME
    cfg["claudeDir"] = CLAUDE_DIR
    cfg["configPath"] = CONFIG_PATH
    cfg["referencesPath"] = _abspath(cfg["references"]["path"])
    cfg["knowledgePath"] = _abspath(cfg["knowledge"]["path"])
    cfg["cachePath"] = os.path.join(CONTEXTKIT_HOME, "cache", "references")
    cfg["isHub"] = os.path.exists(HUB_MARKER)
    return cfg


if __name__ == "__main__":
    import pprint
    pprint.pprint(load())
