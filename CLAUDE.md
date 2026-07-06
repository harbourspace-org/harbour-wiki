# Harbour.Wiki — monorepo

Real-time lecture capture → structured live notes → permanent browsable wiki, accessed by students primarily through MCP.

## Repo layout

| Path | What it is | Stack | Remote |
|---|---|---|---|
| `harbour-wiki/` | The wiki app: keeper of courses → lectures, concept pages with backlinks, ingest gateway (`/api/ingest`), MCP server (`/api/mcp`), web UI | Next.js, pnpm, Railway | part of this repo |
| `capture/` | `lecture-capture` CLI that runs on the lecture PC: mic → whisper → text chunks → gateway | Python, uv | part of this repo |
| `knottra/` | **Git submodule** → `harbourspace-org/knottra`. The real-time fusion engine ("the brain"): raw event stream in, concepts/links/embeddings out. Intended to be open-sourced — keep it generic, no Harbour-specific code | Python, uv, Alembic, Railway | own repo |

Division of labour (hard rule): **Knottra is hierarchy-blind** — it only sees opaque session ids and answers data queries (`/events`, `/record?since=`, semantic search). All course/lecture/student domain logic lives in `harbour-wiki/`. Never leak wiki domain concepts into knottra. See `PIPELINE.md` for the full design.

## Committing & pushing (one command)

Use `scripts/ship.sh "message"` (or the `git ship "message"` alias) — it commits any knottra changes to knottra's own repo, bumps the submodule pointer, commits the monorepo, and pushes once (`push.recurseSubmodules=on-demand` pushes knottra automatically). Prefer this over manual two-step commits.

## Working with the knottra submodule

- Edit code directly in `knottra/` — it's a normal checkout of its own repo.
- Manual flow (what ship.sh automates): commit and push **inside** `knottra/` first (to `harbourspace-org/knottra`), then commit the updated submodule pointer here: `git add knottra && git commit`.
- After `git pull` in this repo: `git submodule update --init` to sync knottra to the pinned commit.
- Fresh clone: `git clone --recurse-submodules`.
- Because knottra may become public: no secrets, no Harbour-internal references in its code or commit messages.

## Dev commands

- `harbour-wiki/`: `pnpm install`, `pnpm dev`, `pnpm build`
- `capture/`: `uv sync`, `uv run lecture-capture --class <course-id>`, `uv run pytest`
- `knottra/`: `uv sync`, `docker compose up` (local DB), `uv run pytest`, migrations via `alembic`

Each subproject keeps its own `.env` (git-ignored); deploys are per-project on Railway (`railway.json` in `harbour-wiki/` and `knottra/`).
