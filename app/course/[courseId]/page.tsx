import Link from "next/link";

import { CourseSearch } from "@/components/CourseSearch";
import { buildCourseGraph } from "@/lib/aggregate";

export default async function CoursePage({ params }: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await params;
  const graph = await buildCourseGraph(courseId).catch(() => null);

  if (!graph) {
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
        <h1>Course not found</h1>
        <p className="muted">This course does not exist yet.</p>
      </main>
    );
  }

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

      <h1>{graph.course.title}</h1>
      <p className="subtitle">
        From Harbour.Wiki — {graph.conceptsById.size} concepts across {graph.lectures.length}{" "}
        lecture{graph.lectures.length === 1 ? "" : "s"}.
      </p>

      <aside className="infobox">
        <CourseSearch courseId={courseId} />
      </aside>

      <nav className="toc">
        <div className="toc-title">Contents</div>
        <ol>
          {graph.lectures.map((lec) => (
            <li key={lec.sessionId}>
              <a href={`#l${lec.number}`}>{lec.label}</a>
              {lec.live && <span className="live-badge">LIVE</span>}
            </li>
          ))}
        </ol>
      </nav>

      {graph.lectures.map((lec) => (
        <section key={lec.sessionId} id={`l${lec.number}`}>
          <h2>
            {lec.number}. {lec.label}
            {lec.live && <span className="live-badge">LIVE</span>}
          </h2>
          {lec.narrative && (
            <details style={{ margin: "0.4rem 0 0.8rem" }}>
              <summary style={{ cursor: "pointer" }}>
                Lecture conspect <span className="muted">(timestamped)</span>
              </summary>
              <p style={{ whiteSpace: "pre-wrap", marginTop: "0.5rem" }}>{lec.narrative}</p>
            </details>
          )}
          {lec.concepts.length === 0 ? (
            <p className="muted">Nothing structured yet{lec.live ? " — the lecture just started." : "."}</p>
          ) : (
            <ul>
              {lec.concepts.map((c) => (
                <li key={c.id}>
                  <Link href={`/course/${courseId}/c/${c.id}`}>{c.title}</Link>
                  {c.detail && (
                    <span className="muted">
                      {" "}
                      — {c.detail.length > 110 ? `${c.detail.slice(0, 110)}…` : c.detail}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      ))}

      <p className="footnote">
        Notes are fused from live capture by the Knottra engine and kept here. Ask questions
        about this course from Claude via the MCP endpoint.
      </p>
    </main>
  );
}
