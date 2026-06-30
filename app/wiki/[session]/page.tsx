import Link from "next/link";

import { SearchAsk } from "@/components/SearchAsk";
import { getRecord } from "@/lib/knottra";
import type { ConceptNode } from "@/lib/types";

const ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"];
const roman = (n: number) => ROMAN[n] ?? String(n + 1);

const MODALITY_CLASS: Record<string, string> = {
  speech: "speech",
  board: "board",
  slide: "slide",
};

function Entry({ concept, index }: { concept: ConceptNode; index: number }) {
  return (
    <article className="entry" style={{ animationDelay: `${index * 90}ms` }}>
      <div className="entry-num">{roman(index)}.</div>
      <div className="entry-body">
        <h2 className="entry-title">{concept.title}</h2>
        {concept.detail && <p className="entry-detail">{concept.detail}</p>}
        {concept.sub_points.length > 0 && (
          <ul className="subpoints">
            {concept.sub_points.map((sp, i) => (
              <li key={i}>{sp.text}</li>
            ))}
          </ul>
        )}
        <div className="tags">
          {concept.modalities.map((m) => (
            <span className={`tag ${MODALITY_CLASS[m] ?? ""}`} key={m}>
              {m}
            </span>
          ))}
          <span className="tag" title="fusion confidence">
            conf {concept.confidence.toFixed(2)}
          </span>
        </div>
      </div>
    </article>
  );
}

export default async function WikiPage({ params }: { params: Promise<{ session: string }> }) {
  const { session } = await params;
  const record = await getRecord(session).catch(() => null);

  const titleOf = (id: string) =>
    record?.concepts.find((c) => c.id === id)?.title ?? null;

  return (
    <main className="shell">
      <header className="masthead">
        <span className="wordmark">
          Harbour<b>.</b>Wiki
        </span>
        <span className="meta">
          <Link className="plain" href="/">
            ← reading room
          </Link>
        </span>
      </header>
      <p className="kicker" style={{ marginTop: "0.8rem" }}>Session · {session}</p>

      {record === null ? (
        <EmptyState session={session} reason="unreachable" />
      ) : record.concepts.length === 0 ? (
        <EmptyState session={session} reason="empty" />
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 22rem", gap: "clamp(1.5rem,1rem+3vw,4rem)", alignItems: "start", marginTop: "1rem" }}>
          <div>
            <p className="dek">
              {record.concepts.length} concepts woven through{" "}
              {record.fused_through_seq} events.
            </p>
            <div className="entries">
              {record.concepts.map((c, i) => (
                <Entry key={c.id} concept={c} index={i} />
              ))}
            </div>
            {record.links.length > 0 && (
              <section style={{ marginTop: "2.5rem", borderTop: "1.5px solid var(--ink)", paddingTop: "1.2rem" }}>
                <p className="label">Connections</p>
                <ul style={{ listStyle: "none", padding: 0, marginTop: "0.6rem" }}>
                  {record.links.map((l) => (
                    <li className="connections" key={l.id} style={{ marginTop: "0.4rem" }}>
                      {titleOf(l.from_concept) ?? "—"} <span className="kind">{l.kind}</span>{" "}
                      {titleOf(l.to_concept) ?? "—"}
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </div>
          <aside>
            <SearchAsk session={session} />
          </aside>
        </div>
      )}
    </main>
  );
}

function EmptyState({ session, reason }: { session: string; reason: "empty" | "unreachable" }) {
  return (
    <div className="panel" style={{ marginTop: "2rem", maxWidth: "46rem" }}>
      <h3>{reason === "empty" ? "No fused record yet" : "Couldn't reach Knottra"}</h3>
      <p className="muted" style={{ marginTop: "0.5rem", lineHeight: 1.6 }}>
        {reason === "empty" ? (
          <>
            Session <b>{session}</b> exists but has no concepts yet. Ingest events
            and flush it (the worker fuses in the background), then refresh.
          </>
        ) : (
          <>
            The Knottra API isn&apos;t responding. Start it (and the worker) — see{" "}
            <span className="formula">knottra/docs/RUNNING.md</span> — then refresh.
          </>
        )}
      </p>
    </div>
  );
}
