import Link from "next/link";

// Student-facing instructions for connecting Claude to Harbour.Wiki via MCP.
// The access key is deliberately NOT printed here — teachers hand out the full
// link (with ?key=) in class; this page explains what to do with it.

export const metadata = { title: "Connect Claude — Harbour.Wiki" };

const ENDPOINT = "https://harbour-wiki-production.up.railway.app/api/mcp";

export default function ConnectPage() {
  return (
    <main className="shell">
      <header className="masthead">
        <span className="wordmark">
          Harbour<b>.</b>Wiki
        </span>
        <span className="meta">
          <Link href="/">← all courses</Link>
        </span>
      </header>

      <h1>Ask the lectures from Claude</h1>
      <p className="subtitle">
        Connect Claude to Harbour.Wiki and ask questions about any lecture — including the one
        happening right now — answered from what was actually taught.
      </p>

      <nav className="toc">
        <div className="toc-title">Contents</div>
        <ol>
          <li>
            <a href="#plugin">One-click plugin for Claude Desktop</a>
          </li>
          <li>
            <a href="#link">Get your connector link</a>
          </li>
          <li>
            <a href="#web">Claude.ai in the browser (Pro/Max)</a>
          </li>
          <li>
            <a href="#desktop">Claude Desktop, manual config (any plan)</a>
          </li>
          <li>
            <a href="#ask">What to ask</a>
          </li>
        </ol>
      </nav>

      <section id="plugin">
        <h2>1. One-click plugin (Claude Desktop, any plan)</h2>
        <p>The easiest way — no config files, no terminal:</p>
        <ul>
          <li>
            <a href="/harbour-wiki.mcpb" download>
              <b>Download the Harbour.Wiki plugin</b>
            </a>{" "}
            (<code>harbour-wiki.mcpb</code>, ~1.4&nbsp;MB).
          </li>
          <li>Double-click the file (or drag it onto Claude Desktop) and press Install.</li>
          <li>Paste the access key your teacher shared when asked, and enable the plugin.</li>
        </ul>
        <p className="muted">
          The plugin talks to this site — you&apos;ll always see the latest lectures without
          updating it.
        </p>
      </section>

      <section id="link">
        <h2>2. Get your connector link</h2>
        <p>
          Your teacher shares the connector link for your course. It looks like this (the part
          after <code>?key=</code> is the access key):
        </p>
        <p className="panel" style={{ overflowWrap: "anywhere" }}>
          <code>{ENDPOINT}?key=…</code>
        </p>
      </section>

      <section id="web">
        <h2>3. Claude.ai in the browser (Pro/Max accounts)</h2>
        <ul>
          <li>
            Open <b>claude.ai → Settings → Connectors</b> and choose <b>Add custom connector</b>.
          </li>
          <li>
            Name: <b>Harbour.Wiki</b> · URL: <b>your connector link</b> from step 1.
          </li>
          <li>In a new chat, open the tools menu and enable Harbour.Wiki.</li>
        </ul>
        <p className="muted">
          Note: custom connectors are not available on free claude.ai accounts — use Claude
          Desktop below instead.
        </p>
      </section>

      <section id="desktop">
        <h2>4. Claude Desktop, manual config (works on any plan)</h2>
        <p>
          Install Claude Desktop, then add this to its config file (Settings → Developer → Edit
          config, or <code>claude_desktop_config.json</code>) — paste your full connector link:
        </p>
        <pre className="panel" style={{ overflowX: "auto" }}>
          {`{
  "mcpServers": {
    "harbour-wiki": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "YOUR_CONNECTOR_LINK_HERE"]
    }
  }
}`}
        </pre>
        <p className="muted">Restart the app afterwards; the Harbour.Wiki tools appear in chat.</p>
      </section>

      <section id="ask">
        <h2>5. What to ask</h2>
        <ul>
          <li>
            <i>“List the courses.”</i> — see what&apos;s available, and which lecture is LIVE.
          </li>
          <li>
            <i>“Get lecture 3 of algorithms — what was covered?”</i>
          </li>
          <li>
            <i>“I missed the start of the live lecture — catch me up.”</i>
          </li>
          <li>
            <i>“Search the course: how do collisions get resolved in hash tables?”</i>
          </li>
        </ul>
        <p className="muted">
          Claude answers only from the structured lecture notes — it cites concepts, and if the
          lectures don&apos;t cover something, it says so.
        </p>
      </section>
    </main>
  );
}
