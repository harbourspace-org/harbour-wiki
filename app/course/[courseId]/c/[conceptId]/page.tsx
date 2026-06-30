import Link from "next/link";

import { Annotations } from "@/components/Annotations";
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
          <span className="wordmark">Harbour<b>.</b>Wiki</span>
        </header>
        <div className="panel" style={{ marginTop: "2rem" }}>
          <h3>Concept not found</h3>
          <p className="muted" style={{ marginTop: "0.5rem" }}>
            It may belong to a lecture that hasn&apos;t been fused yet.
          </p>
        </div>
      </main>
    );
  }

  const outgoing = graph.outgoing.get(conceptId) ?? [];
  const backlinks = graph.backlinks.get(conceptId) ?? [];
  const titleOf = (id: string) => graph.conceptsById.get(id)?.title ?? "(elsewhere)";

  return (
    <main className="shell">
      <header className="masthead">
        <span className="wordmark">Harbour<b>.</b>Wiki</span>
        <span className="meta">
          <Link className="plain" href={`/course/${courseId}`}>← {graph.course.title}</Link>
        </span>
      </header>

      <p className="kicker" style={{ marginTop: "0.8rem" }}>{concept.lecture}</p>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 20rem", gap: "clamp(1.5rem,1rem+3vw,3.5rem)", alignItems: "start", marginTop: "0.5rem" }}>
        {/* Article */}
        <article>
          <h1 style={{ fontFamily: "var(--font-display), serif", fontWeight: 500, fontSize: "var(--text-hero)", lineHeight: 1.06, letterSpacing: "-0.02em", textWrap: "balance" }}>
            {concept.title}
          </h1>
          <div className="tags" style={{ marginTop: "0.9rem" }}>
            {concept.modalities.map((m) => (
              <span className={`tag ${m}`} key={m}>{m}</span>
            ))}
            <span className="tag">conf {concept.confidence.toFixed(2)}</span>
          </div>

          {concept.detail && (
            <p className="entry-detail" style={{ marginTop: "1.4rem", fontSize: "1.1rem" }}>
              {concept.detail}
            </p>
          )}

          {concept.sub_points.length > 0 && (
            <ul className="subpoints" style={{ marginTop: "1.2rem" }}>
              {concept.sub_points.map((sp, i) => (
                <li key={i}>{sp.text}</li>
              ))}
            </ul>
          )}

          {/* Outgoing cross-references */}
          {outgoing.length > 0 && (
            <section style={{ marginTop: "2rem" }}>
              <p className="label">Links</p>
              <ul style={{ listStyle: "none", padding: 0, marginTop: "0.5rem" }}>
                {outgoing.map((l, i) => (
                  <li className="connections" key={i} style={{ marginTop: "0.4rem" }}>
                    <span className="kind">{l.kind}</span>{" "}
                    <Link className="plain" href={`/course/${courseId}/c/${l.to}`}>
                      {titleOf(l.to)}
                    </Link>
                    {l.source === "student" && <span className="muted"> · student link</span>}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </article>

        {/* Obsidian-style rail: backlinks + notes */}
        <aside style={{ position: "sticky", top: "1.5rem", display: "grid", gap: "1.25rem" }}>
          <div className="panel">
            <span className="label">What links here</span>
            {backlinks.length === 0 ? (
              <p className="muted" style={{ marginTop: "0.6rem", fontSize: "0.9rem" }}>
                No backlinks yet.
              </p>
            ) : (
              <ul style={{ listStyle: "none", padding: 0, marginTop: "0.5rem" }}>
                {backlinks.map((l, i) => (
                  <li key={i} style={{ padding: "0.4rem 0", borderTop: i ? "1px solid var(--rule)" : "none" }}>
                    <Link className="plain" href={`/course/${courseId}/c/${l.from}`}>
                      {titleOf(l.from)}
                    </Link>{" "}
                    <span className="connections"><span className="kind">{l.kind}</span></span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="panel">
            <span className="label">Notes</span>
            <Annotations courseId={courseId} conceptId={conceptId} />
          </div>
        </aside>
      </div>
    </main>
  );
}
