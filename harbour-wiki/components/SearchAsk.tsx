"use client";

import { useState } from "react";

import type { SearchHit } from "@/lib/types";

export function SearchAsk({ session }: { session: string }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [answer, setAnswer] = useState<string | null>(null);
  const [loading, setLoading] = useState<"search" | "ask" | null>(null);

  async function runSearch() {
    if (!q.trim()) return;
    setLoading("search");
    setAnswer(null);
    try {
      const r = await fetch(`/api/search?session=${encodeURIComponent(session)}&q=${encodeURIComponent(q)}`);
      const data = await r.json();
      setHits(r.ok ? data.hits : []);
    } finally {
      setLoading(null);
    }
  }

  async function runAsk() {
    if (!q.trim()) return;
    setLoading("ask");
    try {
      const r = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session, question: q }),
      });
      const data = await r.json();
      setAnswer(r.ok ? data.answer : `Error: ${data.error ?? r.status}`);
      setHits(r.ok ? data.hits : []);
    } finally {
      setLoading(null);
    }
  }

  return (
    <div className="panel" style={{ position: "sticky", top: "1.5rem" }}>
      <span className="label">Interrogate the lecture</span>
      <h3 style={{ marginTop: "0.25rem", marginBottom: "0.9rem" }}>Search &amp; ask</h3>
      <textarea
        className="field"
        rows={3}
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="e.g. how do you differentiate x squared?"
        style={{ resize: "vertical" }}
      />
      <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.7rem" }}>
        <button className="btn" onClick={runAsk} disabled={loading !== null}>
          {loading === "ask" ? "Thinking…" : "Ask"}
        </button>
        <button
          className="btn"
          onClick={runSearch}
          disabled={loading !== null}
          style={{ background: "transparent", color: "var(--ink)", borderColor: "var(--rule)" }}
        >
          {loading === "search" ? "Searching…" : "Find concepts"}
        </button>
      </div>

      {answer !== null && (
        <div style={{ marginTop: "1.1rem" }}>
          <span className="label">Grounded answer</span>
          <p className="answer" style={{ marginTop: "0.4rem" }}>{answer}</p>
        </div>
      )}

      {hits !== null && hits.length > 0 && (
        <div style={{ marginTop: "1.1rem" }}>
          <span className="label">Relevant concepts</span>
          {hits.map((h) => (
            <div className="hit" key={h.concept.id}>
              <span className="score">{h.score.toFixed(2)}</span>
              <span>{h.concept.title}</span>
            </div>
          ))}
        </div>
      )}
      {hits !== null && hits.length === 0 && (
        <p className="muted" style={{ marginTop: "1rem", fontSize: "0.9rem" }}>
          Nothing matched yet — has this session been fused?
        </p>
      )}
    </div>
  );
}
