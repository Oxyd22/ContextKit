# ContextKit — Hub (blueprint source)

> This folder is the ContextKit **hub**, not a working project.
> Marker: `.claude/contextkit/.hub`. Install into a project, and migrate an installed project, from here.

## What ContextKit is

A project-rooted assistant for a code project. **Working-directory independence:** each skill resolves the project root by walking up from the working directory until it finds `.claude/contextkit` (it uses `CLAUDE_PROJECT_DIR` when that variable already points at the root). Scripts self-locate from their own file path. Both work from any working directory, in Claude Code.

The SessionStart hook (branch ticket, hygiene reminder) is Claude Code only. Elsewhere, `/ck-doctor` gives the same overview on demand. Reference repos are condensed **read-only** into contracts, API specs, and parity. The knowledge base is **read/write**.

## What you do here (in the hub)

- **`/ck-setup`** — install into a project **and** configure it (asks for the project path and platform, copies `.claude/`, sets git exclude, writes the config).
- **`/ck-migrate <path>`** — update an installed project to this hub version. `contextkit.config.json` and the index `cache/` stay.

## Rules in the hub

- Work on the **blueprint** here, not on one concrete project.
- Project skills (`/ck-read-note`, `/ck-create-note`, `/ck-refs-lookup`, `/ck-refs-sync`, `/ck-doctor`) take effect in the **installed project**.
- `.hub` and `install.py` are never copied into a target (`install.py` enforces that). `VERSION` is copied.
- Keep paths relative. No machine-specific details — the blueprint stays portable.
- On every `VERSION` bump, check whether skills or scripts still contain workarounds a newer model now handles unaided. Delete the extra harness. See the note in `ck-migrate/SKILL.md`.

## Topology (after install)

Details in `README.md`. Short form: `<project>/.claude/` is the live copy (gitignored on that machine), `../references/` is read-only, `../project-knowledge/` is read/write.

## Xcode integration (only when platform=ios)

Skills also run in Xcode's agent. One time: **Intelligence → Plug-ins → Add Plug-in → Import from Claude Code**. That imports the skills. The SessionStart hook stays in Claude Code; in the Xcode agent, run `/ck-doctor` for the same overview. Setup looks for a `.xcodeproj` or `.xcworkspace` only in this case.
