# Deploying Harbour.Wiki on Railway

Deploy **Knottra first** (see `knottra/docs/DEPLOY-RAILWAY.md`) — this app
talks to it. Harbour.Wiki is a single Next.js service.

## Service

- **New Service → Deploy from this repo.** Railway reads `railway.json`
  (Nixpacks: `pnpm build` then `pnpm start`, binding `$PORT`).

## Variables

| Variable | Value |
|---|---|
| `KNOTTRA_BASE_URL` | The Knottra **API** service's public URL, e.g. `https://knottra-api-production.up.railway.app` (engine is API-key protected) |
| `KNOTTRA_API_KEY` | One of the keys in the engine's `KNOTTRA_API_KEYS` |
| `APP_DATABASE_URL` | `${{Postgres.DATABASE_URL}}` — same Postgres as the engine; this app uses its own `harbour_wiki` schema |
| `MCP_BEARER_TOKEN` | A strong token — required to query the MCP endpoint |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | Only for the web **Ask** panel (the MCP path uses Claude.ai's own model). Optional. |

> Use the engine's **public** domain for `KNOTTRA_BASE_URL` (simplest). For
> private networking instead, reference the engine over `*.railway.internal`.

## After deploy

- Web wiki: `https://<harbour-wiki-domain>/`
- **MCP endpoint for Claude.ai**: `https://<harbour-wiki-domain>/api/mcp`
  (send `Authorization: Bearer <MCP_BEARER_TOKEN>`).

## Connect Claude.ai

1. Seed/import a course (the demo "Seed demo course" button, or your own
   ingestion into Knottra).
2. Add the MCP endpoint as a connector (see `docs/MCP.md`). For clients that
   support headers (Claude Desktop / Cursor), set the bearer token; for the
   Claude.ai web connector, prefer adding OAuth later.

## Notes

- The app reads `KNOTTRA_BASE_URL` server-side only; the browser never sees the
  engine key, the LLM key, or the MCP token.
- No build-time secrets are required; all config is runtime env.
