#!/usr/bin/env python3
"""SessionStart hook (V2) — context hints at session start.

Self-locating (independent of the working directory). Two modes:
  * Hub     (.hub marker present) → greeting with /ck-setup and /ck-migrate
  * Project (no .hub)             → runtime hints (branch ticket, hygiene)
Prints only when there is something to report.
"""
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contextkit_config as ck

CFG = ck.load()
out = []

if " " in CFG["root"]:
    out.append("⚠️ Project path contains spaces — quote shell commands.")

if CFG["isHub"]:
    out.append("👋 ContextKit blueprint (hub) detected.")
    out.append("   • /ck-setup    → install into a project and configure it")
    out.append("   • /ck-migrate  → update an existing project to this version")
else:
    r = subprocess.run(["git", "-C", CFG["root"], "branch", "--show-current"],
                       capture_output=True, text=True)
    try:
        m = re.search(CFG["ticketPattern"], r.stdout.strip())
    except re.error:
        m = None
        out.append("⚠️ ticketPattern is invalid — run /ck-doctor.")
    if m:
        ticket = m.group(0)
        out.append("🎫 Branch ticket detected: %s → /ck-read-note %s · /ck-create-note %s"
                   % (ticket, ticket, ticket))

    cache = os.path.join(CFG["contextkitHome"], "cache")

    def remind(stamp_name, max_days, label, cmd):
        """Overdue OR never run (missing stamp) → remind."""
        stamp = os.path.join(cache, stamp_name)
        try:
            age = (time.time() - os.path.getmtime(stamp)) / 86400
            if age > max_days:
                out.append("🧹 %s is overdue (%s days) → %s" % (label, int(age), cmd))
        except OSError:
            out.append("🧹 %s has never run → %s" % (label, cmd))

    # Latest wiki events from the log (chronological trace) — when present.
    log_path = os.path.join(CFG["knowledgePath"], "LOG.md")
    try:
        with open(log_path, encoding="utf-8") as f:
            recent = [ln.strip() for ln in f if ln.startswith("## [")][-3:]
        if recent:
            out.append("🧠 Recent knowledge:")
            out += ["   • %s" % ln[3:] for ln in recent]
    except OSError:
        pass

    # Remind only where something is configured — otherwise a fresh project stays quiet.
    if os.path.isdir(CFG["knowledgePath"]):
        remind(".last-knowledge-check", CFG["checkMaxAgeDays"],
               "Knowledge doctor", "/ck-doctor")
    if CFG["references"]["repos"]:
        remind(".last-refresh", CFG["refreshMaxAgeDays"],
               "Reference index", "/ck-refs-sync")

if out:
    print("\n".join(out))
