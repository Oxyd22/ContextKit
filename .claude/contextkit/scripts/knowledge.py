#!/usr/bin/env python3
"""ContextKit knowledge engine (V2) — index and lint for the knowledge base.

The knowledge base is a folder of flat Markdown files (`<id>.md`), each with
minimal YAML frontmatter. This script is the deterministic counterpart of
reindex.py (references): it generates **INDEX.md** and checks the schema,
so the model sees the whole map in *one* read instead of opening every file.
Python standard library only.

Schema (required frontmatter fields):
  id       stable key = file name without .md
  type     default note | decision | ticket — extend via config `schema.types`
  summary  ONE sentence (≤120 characters) — feeds the index without opening the file
  status   only for types that carry a status (config `schema.status`; default
           decision=proposed|accepted|superseded, ticket=open|done). Other types
           have no status.
Optional: related (wikilinks, including block lists), updated/date (a date).

The INDEX header carries `<!-- contextkit:entries=N -->` and no generation
date, so a second run with the same entries is byte-identical.

Usage:
  knowledge.py                     → lint, abort on errors, otherwise rebuild
                                      INDEX.md (default)
  knowledge.py --check             → lint the schema only (exit 1 on errors);
                                      the index is left untouched
  knowledge.py --sync <op> <title> → like the default, then append a LOG.md line
                                      (one call for a complete ingest)
  knowledge.py --log <op> <title>  → append a LOG.md line only
"""
import datetime as _dt
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contextkit_config as ck

CFG = ck.load()
KB = CFG["knowledgePath"]
INDEX = os.path.join(KB, "INDEX.md")
LOG = os.path.join(KB, "LOG.md")
# INDEX.md / LOG.md plus config `knowledge.ignore` (README.md by default).
IGNORED = ck.knowledge_ignored(CFG)
REQUIRED = ("id", "type", "summary")
# Schema comes from the config (DEFAULTS are minimal; a project may extend them).
_SCHEMA = CFG.get("schema") or {}
TYPES = tuple(_SCHEMA.get("types") or ("note", "decision", "ticket"))
STATUS = {k: tuple(v) for k, v in (_SCHEMA.get("status") or {
    "decision": ("proposed", "accepted", "superseded"),
    "ticket": ("open", "done"),
}).items()}  # only these types carry a status; every other type has none
STALE_PROPOSED = CFG.get("staleProposedDays", 21)
STALE_OPEN = CFG.get("staleOpenTicketDays", 30)
# A single new note is not an orphan problem; warn only once the base has a few entries.
ORPHAN_MIN_ENTRIES = 3
TODAY = _dt.date.today().isoformat()

# Machine-readable count. doctor.py parses this exact form.
INDEX_ANCHOR = "<!-- contextkit:entries=%s -->"


def _age_days(fm):
    """Days since `updated` or `date` (YYYY-MM-DD). None when missing or invalid."""
    raw = fm.get("updated") or fm.get("date")
    if not raw:
        return None
    try:
        d = _dt.date.fromisoformat(str(raw).strip()[:10])
    except ValueError:
        return None
    return (_dt.date.today() - d).days


WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")


def _unwrap(v):
    """Strip wrapping quotes from a scalar (YAML-safe "-")."""
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1].strip()
    return v


def _strip_inline_comment(line):
    """Remove a trailing ` #...` comment that sits outside quotes.

    Quoted `#` characters are part of the value (`summary: "keep # this"`).
    A hash that is not preceded by a space is kept.
    """
    quote = None
    i = 0
    while i < len(line):
        c = line[i]
        if quote:
            if c == "\\" and i + 1 < len(line):
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in ("'", '"'):
            quote = c
            i += 1
            continue
        if c == "#" and i > 0 and line[i - 1] == " ":
            return line[:i - 1]
        i += 1
    return line


def parse_frontmatter(path):
    """YAML frontmatter → dict. Scalar `key: value` plus simple lists.

    Scalars are stored as strings. A block list
        related:
          - "[[X]]"
          - Y.md
    is stored as a Python list of raw items. The inline form `[a, b]` stays a
    string (resolved by `related_ids`). No nested YAML beyond that.
    """
    fm = {}
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return fm
    if not lines or lines[0].strip() != "---":
        return fm
    i = 1
    while i < len(lines):
        raw = lines[i]
        if raw.strip() == "---":
            break
        line = _strip_inline_comment(raw)
        if ":" in line and not line.lstrip().startswith("-"):
            k, _, v = line.partition(":")
            k, v = k.strip(), v.strip()
            if v == "":
                # Possible block list: collect following `  - item` lines.
                items, j = [], i + 1
                while j < len(lines):
                    item_raw = lines[j]
                    if item_raw.strip() == "---":
                        break
                    item_line = _strip_inline_comment(item_raw)
                    if not item_line.lstrip().startswith("- "):
                        break
                    items.append(_unwrap(item_line.lstrip()[2:]))
                    j += 1
                if items:
                    fm[k] = items
                    i = j
                    continue
                fm[k] = ""
            else:
                fm[k] = _unwrap(v)
        i += 1
    return fm


def related_ids(fm):
    """`related` field (string, inline list, or block list) → list of entry ids.

    Understands wiki links `[[id]]` and bare file refs `id.md` — including a mix
    in the same string (`"[[a]], b.md, c"`): wiki links are pulled out with a
    regex, and the remainder is also split on commas, instead of accepting only
    ONE form per string. Duplicates are dropped; order is kept.
    """
    raw = fm.get("related", "")
    parts = raw if isinstance(raw, list) else [raw]
    ids, seen = [], set()
    for part in parts:
        part = str(part).strip()
        if not part:
            continue
        found = WIKILINK.findall(part)
        rest = WIKILINK.sub("", part)
        bare = []
        for p in rest.split(","):
            p = p.strip("[]\"' ")
            if not p:
                continue
            bare.append(p[:-3] if p.endswith(".md") else p)
        for rid in found + bare:
            rid = rid.strip()
            if rid and rid not in seen:
                seen.add(rid)
                ids.append(rid)
    return ids


def entries():
    """All <id>.md files (except ignored names) with parsed frontmatter, sorted by id."""
    if not os.path.isdir(KB):
        return []
    out = []
    for name in sorted(os.listdir(KB)):
        if not name.endswith(".md") or name in IGNORED:
            continue
        path = os.path.join(KB, name)
        out.append((name[:-3], path, parse_frontmatter(path)))
    return out


def lint():
    errs, warns = [], []
    rows = entries()
    known = {stem for stem, _p, _fm in rows}
    edges = {}  # stem -> set of valid (known) related targets
    for stem, path, fm in rows:
        targets = set()
        for rid in related_ids(fm):
            if rid == stem:
                continue
            if rid not in known:
                warns.append("%s.md: related '[[%s]]' points at an unknown entry" % (stem, rid))
            else:
                targets.add(rid)
        edges[stem] = targets
        miss = [k for k in REQUIRED if not fm.get(k)]
        if miss:
            errs.append("%s.md: missing fields: %s" % (stem, ", ".join(miss)))
            continue
        if fm["type"] not in TYPES:
            errs.append("%s.md: type '%s' is unknown (%s)" % (stem, fm["type"], "|".join(TYPES)))
        elif fm["type"] in STATUS:  # status-bearing types: required and validated
            if not fm.get("status"):
                errs.append("%s.md: %s requires status (%s)"
                            % (stem, fm["type"], "|".join(STATUS[fm["type"]])))
            elif fm["status"] not in STATUS[fm["type"]]:
                errs.append("%s.md: status '%s' is invalid for %s (%s)"
                            % (stem, fm["status"], fm["type"], "|".join(STATUS[fm["type"]])))
        elif fm.get("status"):  # a type with no status (note/person/workflow) carries one
            warns.append("%s.md: type '%s' has no status, but status is '%s'"
                         % (stem, fm["type"], fm["status"]))
        # Freshness — proposed decisions / open tickets that have sat too long
        age = _age_days(fm)
        if age is not None:
            if fm["type"] == "decision" and fm.get("status") == "proposed" and age > STALE_PROPOSED:
                warns.append("%s.md: 'proposed' for %sd (> %s) — decide or drop"
                             % (stem, age, STALE_PROPOSED))
            elif fm["type"] == "ticket" and fm.get("status") == "open" and age > STALE_OPEN:
                warns.append("%s.md: ticket 'open' for %sd (> %s) — check the status"
                             % (stem, age, STALE_OPEN))
        if fm.get("id") != stem:
            warns.append("%s.md: id '%s' does not match the file name" % (stem, fm.get("id")))
        if len(fm["summary"]) > 120:
            warns.append("%s.md: summary longer than 120 characters (%s)"
                         % (stem, len(fm["summary"])))

    # Graph consistency — backlink symmetry and orphans (the data is already
    # collected above; no second parse pass).
    incoming = {s: set() for s in known}
    for stem, targets in edges.items():
        for rid in targets:
            incoming[rid].add(stem)
    for stem, targets in edges.items():
        for rid in targets:
            if stem not in edges.get(rid, ()):
                warns.append("%s.md: links to [[%s]], but %s.md does not link back"
                             % (stem, rid, rid))
        if len(known) >= ORPHAN_MIN_ENTRIES and not targets and not incoming[stem]:
            warns.append("%s.md: no related link in either direction — orphan?" % stem)
    return errs, warns


def reindex():
    if not os.path.isdir(KB):
        print("❌ Knowledge folder is missing: %s — run /ck-setup." % KB)
        return 1
    order = list(TYPES) + ["?"]  # configured types in config order, the rest last
    groups = {t: [] for t in order}
    rows = entries()
    for stem, _path, fm in rows:
        t = fm.get("type") if fm.get("type") in TYPES else "?"
        summary = fm.get("summary", "(no summary)")
        badge = "(%s) " % fm.get("status", "?") if t in STATUS else ""
        groups[t].append("- [[%s]] %s— %s" % (stem, badge, summary))
    titles = {"decision": "Decisions", "note": "Notes", "ticket": "Tickets", "?": "Uncategorized"}
    # No generation date: a second run with the same entries must be byte-identical.
    body = ["# Knowledge Index — %s entries" % len(rows),
            INDEX_ANCHOR % len(rows),
            "",
            "> Read this first. Then open only the entries that match.",
            "> Generated by knowledge.py — do not edit by hand.",
            ""]
    for t in order:
        if groups[t]:
            body.append("## %s" % titles.get(t, t.capitalize() + "s"))
            body += sorted(groups[t])
            body.append("")
    with open(INDEX, "w", encoding="utf-8") as f:
        f.write("\n".join(body).rstrip() + "\n")
    print("✅ INDEX.md rebuilt — %s entries (%s)" % (len(rows), KB))
    return 0


def log_event(op, title):
    """Append ONE line to LOG.md — a chronological, append-only trace.

    Format `## [YYYY-MM-DD] <op> | <title>`, so `grep "^## \\[" LOG.md | tail -5`
    returns the latest events. LOG.md is a special file (not a knowledge entry).
    """
    if not os.path.isdir(KB):
        print("❌ Knowledge folder is missing: %s — run /ck-setup." % KB)
        return 1
    line = ("## [%s] %s | %s" % (TODAY, op, title)).rstrip()
    new = not os.path.exists(LOG)
    with open(LOG, "a", encoding="utf-8") as f:
        if new:
            f.write("# Knowledge Log — chronological, append-only\n\n"
                    "> Each line: `## [YYYY-MM-DD] <op> | <title>`. "
                    "Latest: `grep \"^## \\[\" LOG.md | tail -5`.\n"
                    "> Generated by knowledge.py — append only, do not rewrite.\n\n")
        f.write(line + "\n")
    print("✅ LOG.md += %s" % line)
    return 0


def _op_title(flag):
    rest = sys.argv[sys.argv.index(flag) + 1:]
    op = rest[0] if rest else "note"
    title = " ".join(rest[1:]).strip() if len(rest) > 1 else "(no title)"
    return op, title


def main():
    ck.abort_on_config_error(CFG)
    if "--log" in sys.argv:
        op, title = _op_title("--log")
        sys.exit(log_event(op, title))
    if "--check" in sys.argv:
        errs, warns = lint()
        for w in warns:
            print("⚠️  %s" % w)
        for e in errs:
            print("❌ %s" % e)
        if not errs and not warns:
            print("✅ Schema ok — %s entries" % len(entries()))
        sys.exit(1 if errs else 0)

    sync = "--sync" in sys.argv
    errs, warns = lint()
    for w in warns:
        print("⚠️  %s" % w)
    for e in errs:
        print("❌ %s" % e)
    if errs:
        print("❌ Schema errors — index not rebuilt, no log entry.")
        sys.exit(1)
    rc = reindex()
    if rc != 0 or not sync:
        sys.exit(rc)
    op, title = _op_title("--sync")
    sys.exit(log_event(op, title))


if __name__ == "__main__":
    main()
