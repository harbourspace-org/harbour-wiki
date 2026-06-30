import Link from "next/link";

import { CourseSearch } from "@/components/CourseSearch";
import { buildCourseGraph } from "@/lib/aggregate";

export default async function CoursePage({ params }: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await params;
  const graph = await buildCourseGraph(courseId).catch(() => null);

  return (
    <main className="shell">
      <header className="masthead">
        <span className="wordmark">
          Harbour<b>.</b>Wiki
        </span>
        <span className="meta">
          <Link className="plain" href="/">← reading room</Link>
        </span>
      </header>

      {!graph ? (
        <div className="panel" style={{ marginTop: "2rem" }}>
          <h3>Course not found</h3>
          <p className="muted" style={{ marginTop: "0.5rem" }}>
            Seed the demo course from the reading room, or create one.
          </p>
        </div>
      ) : (
        <>
          <p className="kicker" style={{ marginTop: "0.8rem" }}>Course · {graph.course.id}</p>
          <h1 style={{ fontFamily: "var(--font-display), serif", fontWeight: 500, fontSize: "var(--text-hero)", lineHeight: 1.05, letterSpacing: "-0.02em" }}>
            {graph.course.title}
          </h1>
          <p className="dek" style={{ marginTop: "0.8rem" }}>
            {graph.conceptsById.size} concepts across {graph.lectures.length} lecture
            {graph.lectures.length === 1 ? "" : "s"}, woven into one wiki.
          </p>

          <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 22rem", gap: "clamp(1.5rem,1rem+3vw,4rem)", alignItems: "start", marginTop: "2.5rem" }}>
            <div>
              {graph.lectures.map((lec) => (
                <section key={lec.sessionId} style={{ marginBottom: "2.5rem" }}>
                  <h2 style={{ fontFamily: "var(--font-display), serif", fontSize: "1.4rem", borderBottom: "1px solid var(--rule)", paddingBottom: "0.4rem", marginBottom: "0.8rem" }}>
                    {lec.label}
                  </h2>
                  {lec.concepts.length === 0 ? (
                    <p className="muted" style={{ fontSize: "0.9rem" }}>Not fused yet.</p>
                  ) : (
                    <ul style={{ listStyle: "none", padding: 0 }}>
                      {lec.concepts.map((c) => (
                        <li key={c.id} style={{ padding: "0.5rem 0", borderBottom: "1px solid var(--rule)" }}>
                          <Link className="plain" href={`/course/${courseId}/c/${c.id}`} style={{ fontFamily: "var(--font-display), serif", fontSize: "1.1rem" }}>
                            {c.title}
                          </Link>
                          <div className="tags" style={{ marginTop: "0.3rem" }}>
                            {c.modalities.map((m) => (
                              <span className={`tag ${m}`} key={m}>{m}</span>
                            ))}
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              ))}
            </div>
            <aside style={{ position: "sticky", top: "1.5rem" }}>
              <CourseSearch courseId={courseId} />
            </aside>
          </div>
        </>
      )}
    </main>
  );
}
