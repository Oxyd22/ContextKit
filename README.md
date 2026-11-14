# ContextKit

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python >= 3.9](https://img.shields.io/badge/python-%E2%89%A53.9-blue.svg)](#requirements)

A **second brain for a code project**. The model (Claude Code) keeps it: decisions and notes stay in small Markdown files, and reference repos are condensed so the model looks them up.

## Table of contents

- [Why](#why)
- [Features](#features)
- [Quickstart](#quickstart)
- [Requirements](#requirements)
- [Installation / Update / Uninstall](#installation--update--uninstall)
- [Commands](#commands)
- [Config reference](#config-reference)
- [Xcode integration (platform=ios)](#xcode-integration-platformios)
- [Running the tests](#running-the-tests)
- [License](#license)

## Why

Without a fixed place, the model forgets *why* something was built and re-reads half a repo on every question. ContextKit gives the project a memory:

- **Knowledge and decisions** — small Markdown entries, each with a one-sentence `summary`. The model reads one generated `INDEX.md` and already knows earlier decisions before it makes a new one.
- **References** — other repos (read-only) are condensed to contracts, API specs, and parity (`repo@sha`). The model looks up the index.

Everything is Markdown the model reads and writes. No server, no database. Install is **fully local**: nothing is committed to the team repo.

> Inspired by Andrej Karpathy's [LLM wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f): keep a persistent, growing wiki, compile knowledge once, and maintain it, in the spirit of "write to disk, not to context" (`INDEX.md`, an append-only `LOG.md`, and a separate git repo for the knowledge base). ContextKit is that idea applied to a code project.

## Features

- **Knowledge and decisions**: small Markdown entries, each with a one-sentence `summary`. The model reads one generated `INDEX.md` and already knows earlier decisions before it makes a new one.
- **References**: other repos (read-only) are condensed to contracts, API specs, and parity (`repo@sha`). The model looks up the index instead of re-reading the repo.
- **SessionStart hook**: at the start of a Claude Code session, the hook can read a ticket id from the current branch name and point at the matching note. Where a knowledge folder or reference repos are configured, it also reminds you when `/ck-doctor` or `/ck-refs-sync` is overdue.
- **`/ck-*` skills**: seven in total. In the project: `/ck-read-note`, `/ck-create-note`, `/ck-doctor`, `/ck-refs-lookup`, `/ck-refs-sync`. `/ck-setup` installs from the hub and reconfigures inside a project. `/ck-migrate` updates a project from the hub.
- **Platform key**: `generic` (default), `ios`, `android`, or `web`. It shapes the parity heading in the reference index. The Xcode project check runs only when the platform is `ios`.
- **Local and dependency-free**: no server, no database, Python standard library only. Nothing is committed to the team repo.

## Quickstart

1. Put the ContextKit hub folder next to your project (see the layout under [Installation](#installation--update--uninstall)).
2. Start a Claude Code session **on the hub** and run `/ck-setup`. It asks for the project path, the platform, the skill location, the reference repos, the knowledge folder, and the ticket pattern.
3. From then on, work **in the project**. Build the first reference index with `/ck-refs-sync`.

Requirements: Python >= 3.9 (standard library only), git, Claude Code, and macOS or Linux. On Windows, use WSL or Git Bash.

> **Claude Code only: the SessionStart hook.** The hook that reads the branch ticket and shows hygiene reminders runs only in Claude Code. Xcode imports the skills but not the hook (see [Xcode integration](#xcode-integration-platformios)); run `/ck-doctor` there instead.

## Requirements

- Python >= 3.9, standard library only (no third-party packages)
- git
- Claude Code
- macOS or Linux with a POSIX shell. On Windows, use WSL or Git Bash.

## Installation / Update / Uninstall

### Install

1. Put the ContextKit hub folder next to the project (the layout below is the default; paths are configurable).
2. Start a Claude Code session **on the hub** and run `/ck-setup`.
3. The skill asks for the project path, the platform (`generic` by default, or `ios`, `android`, `web`), where to put the skills, the reference folder, which repos to index, the knowledge folder, and the ticket pattern. It installs without overwriting existing project files and writes `.claude/contextkit/contextkit.config.json` (`setup.py --write`, including `--platform`).
4. From then on, work **in the project**. Build the first reference index there with `/ck-refs-sync`.

Skills can be installed **globally** (`~/.claude/skills/`, private, available in every project) or **locally** (`<project>/.claude/skills/`, git-excluded). Copies, never symlinks.

`/ck-setup` in an already installed project only reconfigures it. A fresh install starts from the hub.

### Update

Start a session on the hub and run `/ck-migrate` with the project path. Scripts, skills, and `VERSION` are refreshed. `contextkit.config.json` and the index cache stay.

### Uninstall

Remove the installed pieces:

- `.claude/contextkit/`
- the `ck-*` skill folders (under `<project>/.claude/skills/` or `~/.claude/skills/`, depending on where `/ck-setup` put them)
- the ContextKit SessionStart hook entry in `.claude/settings.local.json`
- the ContextKit block in `CLAUDE.local.md` (delete the file if that block is all it contains)
- the ContextKit lines in `.git/info/exclude`

Leave the knowledge folder and the reference repos if you still want them. They live outside `.claude/` by default.

### Which folders go where

```
<parent>/
├── contextkit/                 # HUB — stays; install and migrate from here
│   └── .claude/
│       ├── skills/             # skills (blueprint source)
│       └── contextkit/         # tooling + config (copied into the project)
│
├── <project>/                  # your code — Claude Code project root
│   ├── .claude/
│   │   ├── skills/             # ContextKit skills (or global in ~/.claude/skills/)
│   │   └── contextkit/         # installed tooling + config  (gitignored)
│   └── CLAUDE.local.md         # local context               (gitignored)
│
├── references/                 # read-only reference repos
└── project-knowledge/          # read/write knowledge base (its own git repo)
```

`references/` and `project-knowledge/` sit **beside** the project by default. Both paths are free in the config. ContextKit's own files inside the project are gitignored.

## Commands

In the **project**:

| Command | Purpose |
|---|---|
| `/ck-read-note <question>` | Look up knowledge and decisions (reads the `INDEX` first) |
| `/ck-create-note <…>` | Record a note, decision, or ticket |
| `/ck-doctor` | Check the knowledge base: schema lint + rebuild the index |
| `/ck-refs-lookup <topic>` | Look up the reference repos |
| `/ck-refs-sync` | `git pull` the references and refresh the index |
| `/ck-setup` | Reconfigure this project (no reinstall) |

In the **hub**:

| Command | Purpose |
|---|---|
| `/ck-setup` | Install into a project and configure it |
| `/ck-migrate <path>` | Update an installed project to this version |

## Config reference

File: `.claude/contextkit/contextkit.config.json`. Missing keys fall back to the defaults in `contextkit_config.py`. Paths are relative to the project root (the directory that contains `.claude/`).

| Key | Default | Meaning |
|---|---|---|
| `platform` | `"generic"` | Target platform. Known values: `generic`, `ios`, `android`, `web`. Drives the parity heading `Parity ({platform} <-> {repo})`. |
| `references.path` | `"../references"` | Folder of reference repos. |
| `references.repos` | `[]` | Directory names inside `references.path` to index. |
| `knowledge.path` | `"../project-knowledge"` | Knowledge folder (read/write). |
| `knowledge.ignore` | `["README.md"]` | Extra file names in the knowledge folder that are not entries. `INDEX.md` and `LOG.md` are always ignored. |
| `indexScope` | `["contracts", "api-specs", "parity"]` | What `/ck-refs-sync` extracts. |
| `ticketPattern` | `[A-Z][A-Z0-9]+-\d+` | Regex for ticket ids (Jira-style, configurable). Used on the branch name and by `/ck-create-note`. |
| `checkMaxAgeDays` | `7` | Days before the SessionStart hook reminds you to run `/ck-doctor`. |
| `refreshMaxAgeDays` | `14` | Days before the hook reminds you to run `/ck-refs-sync`. |
| `schema.types` | `["note", "decision", "ticket"]` | Entry types. A project may add more (for example `person`, `workflow`). |
| `schema.status` | decision: `proposed`, `accepted`, `superseded`; ticket: `open`, `done` | Allowed status per type. Types absent from this map have no status. |
| `staleProposedDays` | `21` | Lint warning when a `proposed` decision is older than this. |
| `staleOpenTicketDays` | `30` | Lint warning when an `open` ticket is older than this. |

`/ck-setup` writes `platform`, `references`, `knowledge.path`, and (when you change it) `ticketPattern`. Other keys are left as they are, so a project can extend `schema` without the next reconfigure wiping it.

## Xcode integration (platform=ios)

Only when `platform` is `ios`.

In Xcode, once: **Intelligence → Plug-ins → Add Plug-in → Import from Claude Code**. That imports the skills. It does not import the SessionStart hook, so branch-ticket and hygiene reminders in the Xcode agent come from running `/ck-doctor` by hand.

During `/ck-setup`, an iOS project is checked for a `.xcodeproj` or `.xcworkspace` in the project folder. Other platforms skip that check.

## Running the tests

From the hub root:

```bash
python3 -m unittest discover -s tests -v
```

## License

MIT. See [LICENSE](LICENSE).
