import { SessionEntry } from "@/components/SessionEntry";

export default function Home() {
  return (
    <main className="shell">
      <header className="masthead">
        <span className="wordmark">
          Harbour<b>.</b>Wiki
        </span>
        <span className="meta">Est. MMXXVI · Vol. I</span>
      </header>
      <p className="dek" style={{ marginTop: "0.6rem" }}>
        An auto-woven compendium of the lecture hall.
      </p>

      <section style={{ marginTop: "clamp(3rem,2rem+5vw,6rem)", maxWidth: "52rem" }}>
        <p className="kicker">The reading room</p>
        <h1
          style={{
            fontFamily: "var(--font-display), serif",
            fontWeight: 500,
            fontSize: "var(--text-hero)",
            lineHeight: 1.04,
            letterSpacing: "-0.02em",
            textWrap: "balance",
          }}
        >
          Every lecture, woven into one you can read &amp; ask.
        </h1>
        <p style={{ marginTop: "1.5rem", fontSize: "1.1rem", lineHeight: 1.6, color: "var(--ink-soft)", maxWidth: "54ch" }}>
          Speech, board, and slides are fused by the <a className="plain" href="https://github.com/harbourspace-org/knottra">Knottra</a> engine
          into a structured, concept-linked record. Open a session to read its
          compendium, search it by meaning, or ask a question answered straight
          from what was taught.
        </p>
        <SessionEntry />
        <p className="muted" style={{ marginTop: "1.4rem", fontSize: "0.82rem" }}>
          Requires the Knottra API + worker running locally (see knottra/docs/RUNNING.md).
        </p>
      </section>
    </main>
  );
}
