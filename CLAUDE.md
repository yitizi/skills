# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

A collection of self-contained agent **skills** (Claude Code / Codex) for enterprise
dev tooling, tuned for **Windows + Chinese** environments. Each top-level skill
directory is copied as-is into an agent's `skills/` dir. Overview: `README.md` (Chinese).

| Skill | Purpose | Layout |
|-------|---------|--------|
| `atlassian/` | Jira + Confluence + Bitbucket (Server/DC) | `SKILL.md`, `scripts/atl-*.py`, `scripts/*.ps1`, `references/`, `evals/` |
| `teamcity/` | TeamCity builds, config CRUD, diff, export/import | `SKILL.md`, `scripts/tc-*.py`, `scripts/*.ps1`, `scripts/deliverable/`, `artifact/` |
| `jvmdump-analysis/` | Heap dump analysis, Eclipse MAT + jhat cross-check | `SKILL.md`, `scripts/`, `queries/*.oql`, `references/`, `agents/` |

Each skill has a `SKILL.md` (YAML frontmatter `name` + `description` drives auto-triggering)
and a human-facing `README.md`. Unlike gstack, `SKILL.md` here is **hand-written**, not generated.

## Conventions (all skills)

- **Credentials never in commands or chat.** URL/username → `~/.claude/skill-config/<skill>/config.env`;
  password/PAT → `~/.netrc`, read only via `curl --netrc`. Entry via the `*-credential.ps1` WinForms GUI.
- **`.ps1` sources are pure ASCII** — PowerShell 5.1 parses BOM-less files as GBK, so non-ASCII
  strings break scripts. Docs are UTF-8 without BOM.
- Scripts write results to files rather than dumping large output into context.
- Targets: Windows 10/11, PowerShell 5.1+/pwsh 7, Git Bash curl, Python 3.8+.
- No build or test suite; verify Python changes with `python -m py_compile <file>`.
  `atlassian/evals/evals.json` holds skill eval prompts.

## gstack/ — separate repo, not part of this one

The author's local workspace may contain `gstack/` (third-party, `github.com/garrytan/gstack`),
which is **gitignored** and has its own git history. Never `git add gstack`, `git add .`, or
`git add -A` from the root (it would record a broken gitlink). For gstack work, use
`gstack/CLAUDE.md`.
