"use client";

import Link from "next/link";
import { useState } from "react";

type Hit = { conceptId: string; title: string; score: number; lecture: string };

export function CourseSearch({ courseId }: { courseId: string }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [loading, setLoading] = useState(false);

  async function run() {
    if (!q.trim()) return;
    setLoading(true);
    try {
      const r = await fetch(
        `/api/course-search?course=${encodeURIComponent(courseId)}&q=${encodeURIComponent(q)}`,
      );
      const data = await r.json();
      setHits(r.ok ? data.hits : []);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="panel">
      <span className="label">Search the course by meaning</span>
      <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.5rem" }}>
        <input
          className="field"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()}
          placeholder="e.g. limit definition, chain rule…"
        />
        <button className="btn" onClick={run} disabled={loading}>
          {loading ? "…" : "Search"}
        </button>
      </div>
      {hits?.map((h) => (
        <Link className="hit plain" href={`/course/${courseId}/c/${h.conceptId}`} key={h.conceptId} style={{ textDecoration: "none" }}>
          <span className="score">{h.score.toFixed(2)}</span>
          <span style={{ color: "var(--ink)" }}>
            {h.title} <span className="muted" style={{ fontSize: "0.78rem" }}>· {h.lecture}</span>
          </span>
        </Link>
      ))}
      {hits !== null && hits.length === 0 && (
        <p className="muted" style={{ marginTop: "0.8rem", fontSize: "0.9rem" }}>No matches.</p>
      )}
    </div>
  );
}
