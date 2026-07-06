# Harbour.Wiki plugin for Claude Desktop

A one-file MCP Bundle (`.mcpb`) students install by double-clicking — it
bridges Claude Desktop (stdio) to the hosted `/api/mcp` endpoint via
`mcp-remote`, asking for the access key once at install time.

## Rebuild

```bash
cd extension
npm install --omit=dev
npx -y @anthropic-ai/mcpb pack . ../public/harbour-wiki.mcpb
```

The packed bundle is committed at `public/harbour-wiki.mcpb` and served by the
site at `/harbour-wiki.mcpb` (linked from `/connect`). The bundle only contains
the bridge — tools live on the server, so server updates need no re-install.
Bump `version` in `manifest.json` when changing the bundle itself.
