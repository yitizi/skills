# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

`D:\work\demos\skills` is a **local workspace repository**. It is a thin local wrapper
whose only substantial contents live in [`gstack/`](gstack/) — a **separate, third-party
git repository** (origin `https://github.com/garrytan/gstack.git`, branch `main`,
currently `v0.13.0.0`). The two repositories have **independent git histories**.

This file documents the workspace boundary and points to gstack's own docs. For the
project's real commands, architecture, and conventions, read the gstack docs listed
below rather than re-deriving them.

## The git boundary — read before running any git command

- The outer repo (this directory) and `gstack/` are **two different repositories**.
  `gstack/.git` belongs to the upstream project — never re-initialize, reset, or commit
  it into the outer repo.
- `gstack/` is **gitignored by the outer repo**, so it is never staged here. **Never run
  `git add gstack`, `git add .`, or `git add -A` from the root** — otherwise git records
  `gstack` as a broken embedded gitlink instead of real files.
- **Know which repo you're in.** At the root, git commands act on the outer workspace
  repo. After `cd gstack`, git/bun/test commands act on the upstream gstack repo. When in
  doubt: `git -C <dir> rev-parse --show-toplevel`.
- Editing a file under `gstack/` changes the upstream checkout's working tree (its own git
  tracks that); editing a file at the root changes this workspace repo.

## gstack in one paragraph

gstack ("Garry's Stack") turns Claude Code into a virtual engineering team: ~28 Markdown
**skills** (each a `SKILL.md` giving the agent a role — `/office-hours`, `/plan-ceo-review`,
`/review`, `/qa`, `/ship`, `/cso`, …) plus two compiled Bun CLIs — **`browse`** (a fast
headless Chromium daemon) and **`design`** (GPT Image mockups) — and a Chrome **extension**.
It is a Bun monorepo. Full skill catalog and rationale: `gstack/README.md`, `gstack/AGENTS.md`.

## Where to look (gstack's own docs)

| File | Use it for |
|------|-----------|
| `gstack/CLAUDE.md` | **Start here for gstack work.** Authoritative command list, test tiers (gate vs periodic), the SKILL.md template workflow, commit / CHANGELOG conventions. |
| `gstack/ARCHITECTURE.md` | *Why* it's built this way — the browser daemon model (CLI → localhost HTTP → Chromium over CDP), why Bun, the security model. |
| `gstack/README.md` | Product overview, install, full skill list. |
| `gstack/CONTRIBUTING.md` | Contribution workflow. |
| `gstack/ETHOS.md` | Builder philosophy ("Boil the Lake", "Search Before Building"). |

## Common commands (run from inside `gstack/`)

```bash
cd gstack
bun install              # install dependencies
bun test                 # fast, free tests (skill validation + browse) — run before commits
bun test <path/to.test.ts>   # run a single test file
bun test -t "<pattern>"  # run only tests whose name matches a pattern
bun run build            # regenerate SKILL.md docs + compile the browse/design binaries
bun run gen:skill-docs   # regenerate SKILL.md files from their .tmpl templates
bun run skill:check      # health dashboard / validation across all skills
bun run test:evals       # paid LLM-judge + E2E evals (needs ANTHROPIC_API_KEY; ~$4/run)
```

`SKILL.md` files are **generated** — edit the matching `*.tmpl`, then run
`bun run gen:skill-docs`; never hand-edit a generated `SKILL.md`. The full command
reference and the gate-vs-periodic eval tiering live in `gstack/CLAUDE.md`.

## Platform notes — this workspace runs on Windows (win32, PowerShell)

- **Build from source here.** The binaries checked into `gstack/browse/dist/` and
  `gstack/design/dist/` are macOS-arm64 only and do **not** run on Windows. `gstack`'s
  `./setup` (and `bun run build`) compile native binaries for this platform.
- **Bash + Node are required on Windows.** `./setup` and `bun run build` invoke bash
  scripts (e.g. `browse/scripts/build-node-server.sh`), and browse uses a Node server on
  Windows — so Git Bash/WSL and Node.js must be present alongside Bun. Run those scripts
  from a bash shell, not PowerShell.
- The browse daemon uses an HTTP health check (not PID checks, which are unreliable in Bun
  binaries on Windows) to detect a live server — see `gstack/ARCHITECTURE.md`.
