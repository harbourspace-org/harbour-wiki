"use client";

import { useEffect, useState } from "react";

type Annotation = { id: string; body: string; author: string | null; created_at: string };

export function Annotations({ courseId, conceptId }: { courseId: string; conceptId: string }) {
  const [items, setItems] = useState<Annotation[]>([]);
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetch(`/api/annotations?course=${encodeURIComponent(courseId)}&concept=${encodeURIComponent(conceptId)}`)
      .then((r) => r.json())
      .then((d) => setItems(d.annotations ?? []))
      .catch(() => {});
  }, [courseId, conceptId]);

  async function add() {
    if (!body.trim()) return;
    setBusy(true);
    try {
      const r = await fetch("/api/annotations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ course: courseId, concept: conceptId, body }),
      });
      const data = await r.json();
      if (r.ok) {
        setItems((prev) => [...prev, data.annotation]);
        setBody("");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ marginTop: "1rem" }}>
      {items.map((a) => (
        <div key={a.id} style={{ borderLeft: "2px solid var(--accent)", padding: "0.3rem 0 0.3rem 0.8rem", margin: "0.6rem 0" }}>
          <p style={{ fontSize: "0.95rem", lineHeight: 1.5 }}>{a.body}</p>
          <span className="muted" style={{ fontSize: "0.7rem" }}>
            {a.author || "anonymous"} · {new Date(a.created_at).toLocaleString()}
          </span>
        </div>
      ))}
      <textarea
        className="field"
        rows={2}
        value={body}
        onChange={(e) => setBody(e.target.value)}
        placeholder="Add a note to this concept…"
        style={{ marginTop: "0.5rem", resize: "vertical" }}
      />
      <button className="btn" onClick={add} disabled={busy} style={{ marginTop: "0.5rem" }}>
        {busy ? "Saving…" : "Add note"}
      </button>
    </div>
  );
}
