import Link from "next/link";

// Student-facing instructions for connecting an AI assistant to Harbour.Wiki
// via MCP. The access key is deliberately NOT printed here — the Tech Team
// shares it with testers; this page explains what to do with it.

export const metadata = { title: "Connect your AI — Harbour.Wiki" };

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

      <h1>Ask the lectures from your AI</h1>
      <p className="subtitle">
        Connect Claude or ChatGPT to Harbour.Wiki and ask questions about any lecture —
        including the one happening right now — answered from what was actually taught.
      </p>

      <nav className="toc">
        <div className="toc-title">Contents</div>
        <ol>
          <li>
            <a href="#access">Get access</a>
          </li>
          <li>
            <a href="#desktop">Claude Desktop — one-click plugin (any plan)</a>
          </li>
          <li>
            <a href="#web">Claude.ai in the browser (Pro/Max)</a>
          </li>
          <li>
            <a href="#chatgpt">ChatGPT (Plus/Pro)</a>
          </li>
          <li>
            <a href="#ask">What to ask</a>
          </li>
        </ol>
      </nav>

      <section id="access">
        <h2>1. Get access</h2>
        <p>
          You need one thing: the <b>access key</b>, shared by the <b>Harbour.Space Tech Team</b>{" "}
          (in the announcement post, or ask us directly). Some setups below use it as part of a
          connector URL:
        </p>
        <p className="panel" style={{ overflowWrap: "anywhere" }}>
          <code>{ENDPOINT}?key=&lt;ACCESS_KEY&gt;</code>
        </p>
        <p className="muted">
          One shared key for the whole test — it unlocks every course on this site. Please
          don&apos;t post it publicly outside Harbour.Space.
        </p>
      </section>

      <section id="desktop">
        <h2>2. Claude Desktop — one-click plugin (works on any plan, including free)</h2>
        <p>The easiest way — no config files, no terminal:</p>
        <ul>
          <li>
            <a href="/harbour-wiki.mcpb" download>
              <b>Download the Harbour.Wiki plugin</b>
            </a>{" "}
            (<code>harbour-wiki.mcpb</code>, ~1.4&nbsp;MB).
          </li>
          <li>Double-click the file (or drag it onto the Claude Desktop window) and press <b>Install</b>.</li>
          <li>Paste the access key when asked, then enable the plugin.</li>
          <li>
            In a new chat, ask <i>“list the courses”</i> — if Claude answers with the course
            list, you&apos;re connected.
          </li>
        </ul>
        <p className="muted">
          The plugin is a thin bridge to this site, so new lectures and features appear without
          reinstalling it. Don&apos;t drop the file into a chat — that only attaches it as a
          document; install it via double-click or the plugins menu.
        </p>
        <details style={{ margin: "0.6rem 0" }}>
          <summary style={{ cursor: "pointer" }}>
            Alternative: manual config (if the plugin doesn&apos;t work for you)
          </summary>
          <p>
            Requires Node.js installed. Open Settings → Developer → <b>Edit Config</b> (this
            opens <code>claude_desktop_config.json</code> — a file, not the chat) and add,
            replacing <code>&lt;ACCESS_KEY&gt;</code>:
          </p>
          <pre className="panel" style={{ overflowX: "auto" }}>
            {`{
  "mcpServers": {
    "harbour-wiki": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "${ENDPOINT}?key=<ACCESS_KEY>"]
    }
  }
}`}
          </pre>
          <p className="muted">Restart Claude Desktop afterwards.</p>
        </details>
      </section>

      <section id="web">
        <h2>3. Claude.ai in the browser (Pro/Max plans only)</h2>
        <p>
          No install at all — but custom connectors are not available on free claude.ai
          accounts (use Claude Desktop above instead).
        </p>
        <ul>
          <li>
            Open <b>claude.ai → Settings → Connectors</b> and choose <b>Add custom connector</b>.
          </li>
          <li>
            Name: <b>Harbour.Wiki</b> · URL: the full connector URL from step 1 (with your
            access key after <code>?key=</code>).
          </li>
          <li>
            In a new chat, open the tools menu (the sliders icon) and make sure Harbour.Wiki is
            enabled.
          </li>
        </ul>
      </section>

      <section id="chatgpt">
        <h2>4. ChatGPT (Plus/Pro plans, developer mode)</h2>
        <ul>
          <li>
            Open <b>Settings → Apps &amp; Connectors → Advanced settings</b> and enable{" "}
            <b>Developer mode</b>.
          </li>
          <li>
            Back in <b>Apps &amp; Connectors</b>, choose <b>Create</b>: name{" "}
            <b>Harbour.Wiki</b>, MCP server URL: the full connector URL from step 1,
            authentication: <b>No authentication</b> (the key is already in the URL).
          </li>
          <li>In a chat, add Harbour.Wiki from the tools menu (Developer mode section).</li>
        </ul>
        <p className="muted">
          ChatGPT&apos;s free plan does not support custom connectors.
        </p>
      </section>

      <section id="ask">
        <h2>5. What to ask</h2>
        <ul>
          <li>
            <i>“List the courses.”</i> — see what&apos;s available, and which lecture is LIVE.
          </li>
          <li>
            <i>“What was covered in lecture 5 of Linux?”</i>
          </li>
          <li>
            <i>“I missed the start of the live lecture — catch me up.”</i>
          </li>
          <li>
            <i>“What was discussed in the last 10 minutes?”</i> — during a live lecture.
          </li>
          <li>
            <i>“Quiz me on lecture 5.”</i> — active-recall questions; answers stay hidden until
            you try.
          </li>
          <li>
            <i>“Search the course: how do backreferences work?”</i>
          </li>
        </ul>
        <p className="muted">
          The assistant answers only from the structured lecture notes — it cites concepts, and
          if the lectures don&apos;t cover something, it says so. Found a bug or have feedback?
          Tell the Tech Team.
        </p>
      </section>
    </main>
  );
}
