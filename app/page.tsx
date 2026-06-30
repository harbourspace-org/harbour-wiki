import Link from "next/link";

import { CourseSeed } from "@/components/CourseSeed";
import { SessionEntry } from "@/components/SessionEntry";
import { listCourses } from "@/lib/courses";

export default async function Home() {
  const courses = await listCourses().catch(() => []);
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
        <div style={{ marginTop: "2.5rem" }}>
          <p className="label">Courses</p>
          {courses.length > 0 ? (
            <ul style={{ listStyle: "none", padding: 0, marginTop: "0.6rem" }}>
              {courses.map((c) => (
                <li key={c.id} style={{ padding: "0.5rem 0", borderBottom: "1px solid var(--rule)" }}>
                  <Link className="plain" href={`/course/${c.id}`} style={{ fontFamily: "var(--font-display), serif", fontSize: "1.2rem" }}>
                    {c.title}
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted" style={{ marginTop: "0.5rem", fontSize: "0.92rem" }}>
              No courses yet. Seed the demo to see a woven lecture wiki.
            </p>
          )}
          <div style={{ marginTop: "1rem" }}>
            <CourseSeed />
          </div>
        </div>

        <div style={{ marginTop: "2.5rem", paddingTop: "1.5rem", borderTop: "1px solid var(--rule)" }}>
          <p className="label">Or open a single session directly</p>
          <SessionEntry />
        </div>
        <p className="muted" style={{ marginTop: "1.4rem", fontSize: "0.82rem" }}>
          Requires the Knottra API + worker running locally (see knottra/docs/RUNNING.md).
        </p>
      </section>
    </main>
  );
}
