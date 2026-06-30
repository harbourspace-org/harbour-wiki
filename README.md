# Harbour.Wiki

**The auto-built, living wiki of everything taught at Harbour.Space.**

Harbour.Wiki is the student-facing app. It turns lectures into a structured,
concept-linked, askable knowledge base — so a student can catch up on a class
they missed and ask questions grounded in what was actually taught.

## How it fits together

```
Capture + transcription/OCR   (lecture audio, board, slides → text events)
        │
        ▼
   Knottra  ── the fusion engine (separate repo: ../knottra) ──
   weaves the unsynchronized streams into a structured record
   (concepts · sub-points · logical links) and serves it back
        │
        ▼
Harbour.Wiki  (this repo)
   • renders the record as a navigable per-course wiki
   • answers student questions with its own LLM, grounded in
     Knottra's structured slices (Knottra returns DATA, not answers)
```

Knottra is the engine (infrastructure); Harbour.Wiki is the product students
use. This repo consumes Knottra's API — it does **not** reimplement fusion.

## Stack

Next.js (App Router) · TypeScript · Tailwind v4 · pnpm. Server routes hold the
Knottra API key and the answer LLM; the browser never sees secrets. Design
direction: "Editorial Almanac" — paper/ink palette, Fraunces + IBM Plex.

## Run locally

```bash
# 1) Start the Knottra engine (separate repo)
cd ../knottra && docker compose up -d db
uv run python -m uvicorn knottra.main:app --port 8000 &
uv run procrastinate --app knottra.worker.app.procrastinate_app worker --queues fusion,maintenance &

# 2) Start this app
cd ../harbour-wiki
cp .env.example .env.local   # set KNOTTRA_API_KEY + LLM_API_KEY
pnpm install
pnpm dev                     # http://localhost:3000
```

Open the app, click **Seed demo lecture** (ingests a sample lecture and flushes
it — the worker fuses it), then read the compendium, search it, or ask a
question. The `/api/*` routes proxy Knottra (`/record`, `/search`) and run the
grounded-answer LLM.

## What it consumes

- `GET /v1/sessions/{id}/record` — the fused concepts/links (rendered as entries)
- `GET /v1/sessions/{id}/record/search?q=` — semantic search (the search panel)
- `POST /v1/sessions/{id}/events` + `/flush` — the demo seed
- The answer LLM is grounded **only** in Knottra's structured slices.

## Related

- `../knottra` — the multi-stream temporal context fusion engine (the core).
