// Thin stdio→HTTP bridge: Claude Desktop runs this bundled entry point, which
// proxies MCP over stdio to the hosted Harbour.Wiki endpoint via mcp-remote.
const { spawn } = require("node:child_process");
const path = require("node:path");

const key = process.env.HARBOUR_WIKI_KEY;
if (!key) {
  process.stderr.write("harbour-wiki: HARBOUR_WIKI_KEY is not set\n");
  process.exit(1);
}

const url = `https://harbour-wiki-production.up.railway.app/api/mcp?key=${encodeURIComponent(key)}`;
const proxy = path.join(__dirname, "..", "node_modules", "mcp-remote", "dist", "proxy.js");

const child = spawn(process.execPath, [proxy, url], { stdio: "inherit" });
child.on("exit", (code) => process.exit(code ?? 1));
child.on("error", (err) => {
  process.stderr.write(`harbour-wiki: failed to start proxy: ${err.message}\n`);
  process.exit(1);
});
