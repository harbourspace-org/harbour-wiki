import Link from "next/link";

import { AskBox } from "@/components/AskBox";
import { CourseSearch } from "@/components/CourseSearch";
import { FeedbackButtons } from "@/components/FeedbackButtons";
import { LiveBadge } from "@/components/LiveBadge";
import { LiveRefresh } from "@/components/LiveRefresh";
import { Md } from "@/components/Markdown";
import { buildCourseGraph } from "@/lib/aggregate";
import { splitConspect } from "@/lib/narrative";
import { logUsage } from "@/lib/usage";

export default async function CoursePage({ params }: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await params;
  const graph = await buildCourseGraph(courseId).catch(() => null);
  if (graph) logUsage("web", "course_view", courseId);

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
      {graph.lectures.some((l) => l.live) && <LiveRefresh courseId={courseId} />}
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

      <aside className="infobox">
        <span className="label">Ask the course</span>
        <AskBox courseId={courseId} />
      </aside>

      <nav className="toc">
        <div className="toc-title">Contents</div>
        <ol>
          {graph.lectures.map((lec) => (
            <li key={lec.sessionId}>
              <a href={`#l${lec.number}`}>{lec.label}</a>
              <LiveBadge live={lec.live} receiving={lec.receiving} silentFor={lec.silentFor} />
            </li>
          ))}
        </ol>
      </nav>

      {graph.lectures.map((lec) => {
        const conspect = lec.narrative ? splitConspect(lec.narrative) : null;
        return (
        <section key={lec.sessionId} id={`l${lec.number}`}>
          <h2>
            {lec.number}. {lec.label}
            <LiveBadge live={lec.live} receiving={lec.receiving} silentFor={lec.silentFor} />
          </h2>
          {conspect && conspect.takeaways.length > 0 && (
            <div className="takeaways">
              <span className="takeaways-label">What to remember</span>
              <ul>
                {conspect.takeaways.map((t, i) => (
                  <li key={i}>
                    <Md text={t} inline />
                  </li>
                ))}
              </ul>
            </div>
          )}
          {conspect && conspect.quiz.length > 0 && (
            <div className="selfcheck">
              <span className="selfcheck-label">Check yourself</span>
              {conspect.quiz.map((q, i) => (
                <details key={i}>
                  <summary>
                    <Md text={q.question} inline />
                  </summary>
                  <Md text={q.answer} />
                </details>
              ))}
            </div>
          )}
          {conspect && (
            <details style={{ margin: "0.4rem 0 0.8rem" }}>
              <summary style={{ cursor: "pointer" }}>
                Lecture conspect <span className="muted">(timestamped)</span>
              </summary>
              <div style={{ marginTop: "0.5rem" }}>
                <Md text={conspect.body} breaks />
              </div>
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
                      — <Md text={c.detail.length > 110 ? `${c.detail.slice(0, 110)}…` : c.detail} inline />
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
        );
      })}

      <FeedbackButtons courseId={courseId} />

      <p className="footnote">
        Notes are fused from live capture by the Knottra engine and kept here. Ask questions
        about this course from Claude via the MCP endpoint.
      </p>
    </main>
  );
}
