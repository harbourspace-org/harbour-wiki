import Link from "next/link";

import { CourseSeed } from "@/components/CourseSeed";
import { listCourses } from "@/lib/courses";
import { courseLectures, isLive } from "@/lib/lectures";

export default async function Home() {
  const courses = await listCourses().catch(() => []);
  const enriched = await Promise.all(
    courses.map(async (c) => {
      const lectures = await courseLectures(c.id).catch(() => []);
      return { ...c, lectures: lectures.length, live: lectures.some(isLive) };
    }),
  );

  return (
    <main className="shell">
      <header className="masthead">
        <span className="wordmark">
          Harbour<b>.</b>Wiki
        </span>
        <span className="meta">the living encyclopedia of the lecture hall</span>
      </header>

      <h1>Courses</h1>
      <p className="subtitle">
        Every lecture is captured, structured into concepts by the Knottra engine, and kept
        here — readable, searchable, and askable (via MCP) in real time.
      </p>

      {enriched.length > 0 ? (
        <ul>
          {enriched.map((c) => (
            <li key={c.id}>
              <Link href={`/course/${c.id}`}>{c.title}</Link>{" "}
              <span className="muted">
                — {c.lectures} lecture{c.lectures === 1 ? "" : "s"}
              </span>
              {c.live && <span className="live-badge">LIVE</span>}
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">No courses yet.</p>
      )}

      <div className="panel" style={{ marginTop: "2rem", maxWidth: "34rem" }}>
        <span className="label">Try it</span>
        <p className="muted" style={{ margin: "0 0 0.5rem", fontSize: "0.9rem" }}>
          Seed a demo course to see a structured lecture, or record a real one with the
          lecture-capture tool.
        </p>
        <CourseSeed />
      </div>

      <p className="footnote">
        Built on <a href="https://github.com/harbourspace-org/knottra">Knottra</a>, the
        multi-stream fusion engine. Ask questions from Claude via the MCP endpoint.
      </p>
    </main>
  );
}
