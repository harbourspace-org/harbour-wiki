// Thin stdio→HTTP bridge: Claude Desktop runs this bundled entry point, which
// proxies MCP over stdio to the hosted Harbour.Wiki endpoint via mcp-remote.
//
// mcp-remote is loaded IN-PROCESS (dynamic import), never as a child process:
// under Claude Desktop's built-in runtime process.execPath is the Electron
// binary, so spawning it would launch another app instance instead of Node.
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const key = process.env.HARBOUR_WIKI_KEY;
if (!key) {
  process.stderr.write("harbour-wiki: HARBOUR_WIKI_KEY is not set\n");
  process.exit(1);
}

const url = `https://harbour-wiki-production.up.railway.app/api/mcp?key=${encodeURIComponent(key)}`;
const proxy = path.join(__dirname, "..", "node_modules", "mcp-remote", "dist", "proxy.js");

// proxy.js reads the target URL from argv[2] and runs on import.
process.argv = [process.argv[0], "mcp-remote", url];
import(pathToFileURL(proxy).href).catch((err) => {
  process.stderr.write(`harbour-wiki: failed to start proxy: ${err.stack || err}\n`);
  process.exit(1);
});
