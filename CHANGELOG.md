# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.3.0] - 2026-11-14

### Fixed

- The SessionStart hook is synchronous. Async hooks do not inject their stdout, so the branch ticket and the hygiene reminder never reached the model. Install and update drop `async` from an existing ContextKit hook entry.

### Added

- Skill directories written by the installer carry a `.contextkit-owned` marker. An update overwrites or removes a skill directory only when that marker is present, or when the name is listed in `.installed.json` for the same scope. A directory skipped at install time because it already existed is left untouched.
- Global skills record their version in `~/.claude/skills/.contextkit.json`. A hub that is numerically older than that record refuses to install or update unless `--force` is set.
- Each skill resolves the project root before it builds paths: `CLAUDE_PROJECT_DIR` when that already points at the root, otherwise the nearest ancestor that contains `.claude/contextkit`.
- `reindex.py` keeps the cache body when the recorded SHA changes and refreshes only the frontmatter (`sha`, `status: needs-extraction`), so live findings survive a pull.
- `setup.py --create-knowledge` runs `git init` in the knowledge folder when it is not already a git repository.
- Config key `platform` (default `generic`). Known values are `generic`, `ios`, `android`, and `web`; other tokens are allowed. `setup.py --scan` and `--write` accept `--platform` (non-empty, `[a-z0-9_-]+`). The parity stub heading is `Parity ({platform} <-> {repo})`. Stub sections are generated from `indexScope`; the default names `contracts`, `api-specs`, and `parity` keep their headings. Doctor runs the Xcode project check only when `platform` is `ios`.
- `INDEX.md` carries a machine-readable `<!-- contextkit:entries=N -->` line. Doctor reads that anchor. An index without it is reported as outdated so it can be regenerated.
- Unit tests under `tests/` (`python3 -m unittest discover -s tests`). Python standard library only.
- MIT license (`LICENSE`).

### Changed

- User-facing messages, docstrings, and comments in the scripts are English.
- The knowledge index header no longer includes a generation date, so rebuilding it when nothing changed does not produce a git diff.
