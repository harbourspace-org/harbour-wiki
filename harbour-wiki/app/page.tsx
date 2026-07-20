import Link from "next/link";

import { LiveBadge } from "@/components/LiveBadge";
import { listCourses } from "@/lib/courses";
import { courseLectures, isLive, isReceiving, silentForSeconds } from "@/lib/lectures";

// Without this, Next prerenders "/" at BUILD time — no DB in the Docker build,
// so an empty course list gets baked into static HTML. This is a live index.
export const dynamic = "force-dynamic";

export default async function Home() {
  const courses = await listCourses().catch(() => []);
  const enriched = await Promise.all(
    courses.map(async (c) => {
      const lectures = await courseLectures(c.id).catch(() => []);
      const liveRow = lectures.find(isLive) ?? null;
      return {
        ...c,
        lectures: lectures.length,
        live: liveRow !== null,
        receiving: liveRow !== null && isReceiving(liveRow),
        silentFor: liveRow ? silentForSeconds(liveRow) : null,
      };
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
              <LiveBadge live={c.live} receiving={c.receiving} silentFor={c.silentFor} />
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">No courses yet.</p>
      )}

      <p className="footnote">
        Classroom operator? <Link href="/capture">Open capture control</Link>.
        <br />
        Built on <a href="https://github.com/harbourspace-org/knottra">Knottra</a>, the
        multi-stream fusion engine. Ask questions from Claude via the MCP endpoint.
      </p>
    </main>
  );
}
