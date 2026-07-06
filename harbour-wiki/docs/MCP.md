# Harbour.Wiki MCP server

The **primary student interface**: connect a course context inside Claude.ai
(or Claude Desktop / Cursor) and ask questions about the lectures. The MCP
tools return Knottra's **structured slices** (data, not answers); the client's
model (Claude) composes the grounded answer.

This honours the engine's rule — Knottra returns data, the caller's LLM answers.
Here Claude.ai *is* that LLM.

## Endpoint

Streamable HTTP, served by the Next app:

```
POST /api/mcp        (+ GET/DELETE for the session lifecycle)
```

Locally: `http://localhost:3000/api/mcp`. Claude.ai needs a **public URL**, so
expose it via a deploy or a tunnel:

```bash
# example tunnel for local testing
cloudflared tunnel --url http://localhost:3000
# or: ngrok http 3000
```

## Tools

| Tool | Purpose |
|------|---------|
| `list_courses` | Discover course ids (call first) |
| `list_lectures` | Lectures in a course + concept counts |
| `search_lectures` | Semantic search across a course → relevant concepts (the main grounding tool) |
| `get_concept` | One concept + its links and backlinks |
| `get_lecture_record` | A whole lecture's fused record |

## Connect in Claude.ai

1. Deploy the app (or run a tunnel) so the endpoint is reachable over HTTPS.
2. Claude.ai → **Settings → Connectors → Add custom connector**.
3. URL: `https://<your-host>/api/mcp`.
4. If `MCP_BEARER_TOKEN` is set, add header `Authorization: Bearer <token>`.
5. In a chat: *"List the courses, then using the derivatives course, explain how
   to differentiate x²."* Claude calls `search_lectures` and answers from the
   returned concepts.

## Auth

Set `MCP_BEARER_TOKEN` in the environment to require a bearer token. Leave it
empty for open local dev. For production, prefer a real per-student auth layer
(OAuth) — the bearer token is a minimal gate.

## Requirements

The Knottra API must be reachable (`KNOTTRA_BASE_URL`) and the course must be
fused. See `knottra/docs/RUNNING.md`.
