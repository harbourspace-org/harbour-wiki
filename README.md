# Harbour.Wiki

Real-time lecture capture that turns live audio into structured, browsable course notes — and streams them to students through MCP while the lecture is still happening.

A recorder on the lecture-room PC transcribes speech locally and streams text chunks to the wiki. The wiki forwards them to **Knottra**, a real-time fusion engine that incrementally builds concepts, sub-points, and logical links out of the raw stream. The wiki keeps every lecture permanently as interlinked pages (think Obsidian × Wikipedia), and students connect Claude to the MCP endpoint to ask questions grounded in the growing record — with the notes trailing the lecturer by under a minute.

```
[lecture PC]                     [Railway]
lecture-capture ──▶ Harbour.Wiki /api/ingest ──▶ Knottra /events
 mic → whisper           │  (single gateway)         │ fuses concepts/links
 → text chunks           │                           ▼
                         └── pulls deltas (?since=) ── structured record
                                    │
                    ┌───────────────┴───────────────┐
              MCP /api/mcp                      Web wiki
        (students ask Claude,               (browse courses →
         live Q&A during lecture)            lectures → concepts)
```

## Repository layout

| Path | Component | Stack |
|---|---|---|
| [`harbour-wiki/`](harbour-wiki/) | The wiki app: course → lecture hierarchy, concept pages with backlinks, ingest gateway, MCP server, web UI | Next.js (pnpm) |
| [`capture/`](capture/) | `lecture-capture` CLI for the lecture-room PC: mic → local faster-whisper → text chunks → gateway | Python (uv) |
| [`knottra/`](knottra/) | Fusion engine — **git submodule** of [harbourspace-org/knottra](https://github.com/harbourspace-org/knottra), kept as its own repo for open-sourcing | Python (uv), Postgres |

**Division of labour:** Knottra is deliberately *hierarchy-blind* — it fuses opaque sessions and answers data queries only. Everything domain-shaped (courses, lectures, students, pages) lives in Harbour.Wiki. Full design in [`PIPELINE.md`](PIPELINE.md).

## Getting started

```bash
git clone --recurse-submodules https://github.com/harbourspace-org/harbour-wiki.git
cd harbour-wiki

# wiki app
cd harbour-wiki && pnpm install && pnpm dev

# capture CLI
cd capture && uv sync
uv run lecture-capture --class <course-id>

# knottra engine
cd knottra && uv sync && docker compose up   # local Postgres
uv run pytest
```

Each component reads its own `.env` (git-ignored); see the per-directory READMEs for the required variables.

### Working with the knottra submodule

Edit `knottra/` like any checkout: commit and push **inside it** first (goes to its own repo), then record the new pointer here with `git add knottra && git commit`. After pulling this repo, run `git submodule update --init`.

## Deployment

`harbour-wiki` and `knottra` each deploy to Railway from their Dockerfiles via `railway up --detach --service <name>` (no GitHub auto-deploy). `capture` is installed directly on lecture-room machines.
