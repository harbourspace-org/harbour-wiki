import Link from "next/link";

import { SearchAsk } from "@/components/SearchAsk";
import { getRecord } from "@/lib/knottra";
import type { ConceptNode } from "@/lib/types";

function Entry({ concept, index }: { concept: ConceptNode; index: number }) {
  return (
    <section id={`c${index + 1}`}>
      <h2>
        {index + 1}. {concept.title}{" "}
        <span className="tags">
          {concept.modalities.map((m) => (
            <span className={`tag ${m}`} key={m}>
              {m}
            </span>
          ))}
        </span>
      </h2>
      {concept.detail && <p>{concept.detail}</p>}
      {concept.sub_points.length > 0 && (
        <ul>
          {concept.sub_points.map((sp, i) => (
            <li key={i}>{sp.text}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default async function WikiPage({ params }: { params: Promise<{ session: string }> }) {
  const { session } = await params;
  const record = await getRecord(session).catch(() => null);

  const titleOf = (id: string) => record?.concepts.find((c) => c.id === id)?.title ?? null;

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

      <h1>Lecture notes</h1>
      <p className="subtitle">Session {session}</p>

      {record === null ? (
        <p className="muted">Couldn&apos;t reach the engine, or this session doesn&apos;t exist.</p>
      ) : record.concepts.length === 0 ? (
        <p className="muted">
          Nothing structured yet — the lecture may have just started. Refresh in a moment.
        </p>
      ) : (
        <>
          <aside className="infobox">
            <SearchAsk session={session} />
          </aside>

          <nav className="toc">
            <div className="toc-title">Contents</div>
            <ol>
              {record.concepts.map((c, i) => (
                <li key={c.id}>
                  <a href={`#c${i + 1}`}>{c.title}</a>
                </li>
              ))}
            </ol>
          </nav>

          {record.concepts.map((c, i) => (
            <Entry key={c.id} concept={c} index={i} />
          ))}

          {record.links.length > 0 && (
            <section>
              <h2>Connections</h2>
              <ul>
                {record.links.map((l) => (
                  <li className="connections" key={l.id}>
                    {titleOf(l.from_concept) ?? "—"} <span className="kind">{l.kind}</span>{" "}
                    {titleOf(l.to_concept) ?? "—"}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </main>
  );
}
