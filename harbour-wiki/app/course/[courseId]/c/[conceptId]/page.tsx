import Link from "next/link";

import { Annotations } from "@/components/Annotations";
import { Md } from "@/components/Markdown";
import { buildCourseGraph } from "@/lib/aggregate";

export default async function ConceptPage({
  params,
}: {
  params: Promise<{ courseId: string; conceptId: string }>;
}) {
  const { courseId, conceptId } = await params;
  const graph = await buildCourseGraph(courseId).catch(() => null);
  const concept = graph?.conceptsById.get(conceptId) ?? null;

  if (!graph || !concept) {
    return (
      <main className="shell">
        <header className="masthead">
          <span className="wordmark">
            Harbour<b>.</b>Wiki
          </span>
          <span className="meta">
            <Link href={`/course/${courseId}`}>← back to course</Link>
          </span>
        </header>
        <h1>Concept not found</h1>
        <p className="muted">It may belong to a lecture that hasn&apos;t been structured yet.</p>
      </main>
    );
  }

  const outgoing = graph.outgoing.get(conceptId) ?? [];
  const backlinks = graph.backlinks.get(conceptId) ?? [];
  const titleOf = (id: string) => graph.conceptsById.get(id)?.title ?? "(elsewhere)";

  return (
    <main className="shell">
      <header className="masthead">
        <span className="wordmark">
          Harbour<b>.</b>Wiki
        </span>
        <span className="meta">
          <Link href={`/course/${courseId}`}>← {graph.course.title}</Link>
        </span>
      </header>

      <h1>{concept.title}</h1>
      <p className="subtitle">
        From <Link href={`/course/${courseId}`}>{graph.course.title}</Link>, {concept.lecture}{" "}
        <span className="tags" style={{ marginLeft: "0.4rem" }}>
          {concept.modalities.map((m) => (
            <span className={`tag ${m}`} key={m}>
              {m}
            </span>
          ))}
        </span>
      </p>

      {backlinks.length > 0 && (
        <aside className="infobox">
          <span className="label">What links here</span>
          <ul style={{ margin: "0.3rem 0 0 1.2rem" }}>
            {backlinks.map((l, i) => (
              <li key={i}>
                <Link href={`/course/${courseId}/c/${l.from}`}>{titleOf(l.from)}</Link>{" "}
                <span className="connections">
                  <span className="kind">{l.kind}</span>
                </span>
              </li>
            ))}
          </ul>
        </aside>
      )}

      {concept.detail && (
        <div style={{ fontSize: "1.02rem" }}>
          <Md text={concept.detail} />
        </div>
      )}

      {concept.sub_points.length > 0 && (
        <ul>
          {concept.sub_points.map((sp, i) => (
            <li key={i}>
              <Md text={sp.text} inline />
            </li>
          ))}
        </ul>
      )}

      {outgoing.length > 0 && (
        <section>
          <h2>See also</h2>
          <ul>
            {outgoing.map((l, i) => (
              <li key={i}>
                <Link href={`/course/${courseId}/c/${l.to}`}>{titleOf(l.to)}</Link>{" "}
                <span className="connections">
                  <span className="kind">{l.kind}</span>
                </span>
                {l.source === "student" && <span className="muted"> · student link</span>}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h2>Notes</h2>
        <Annotations courseId={courseId} conceptId={conceptId} />
      </section>
    </main>
  );
}
