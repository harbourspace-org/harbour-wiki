"use client";

import Link from "next/link";
import { useState } from "react";

// "Ask this course" for students without a paid Claude plan: the same
// grounded-answer path MCP users get, straight on the course page.

interface AskBoxProps {
  courseId: string;
}

type AskHit = { conceptId: string; title: string; lecture: string };

export function AskBox({ courseId }: AskBoxProps) {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [answer, setAnswer] = useState<string | null>(null);
  const [sources, setSources] = useState<AskHit[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function ask() {
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true);
    setError(null);
    setAnswer(null);
    try {
      const r = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ course: courseId, question: q }),
      });
      const data = await r.json();
      if (!r.ok) {
        setError(data.error ?? `Request failed (${r.status})`);
        return;
      }
      setAnswer(data.answer ?? "(no answer)");
      setSources(data.sources ?? []);
    } catch {
      setError("Network error — try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
        <input
          className="field"
          style={{ flex: "1 1 16rem" }}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && ask()}
          placeholder="Ask anything about this course — answered from the lectures"
          aria-label="Ask the course a question"
        />
        <button className="btn" onClick={ask} disabled={busy || !question.trim()}>
          {busy ? "Thinking…" : "Ask"}
        </button>
      </div>
      {error && <p className="muted ask-answer">⚠ {error}</p>}
      {answer && (
        <div className="ask-answer">
          <p style={{ whiteSpace: "pre-wrap", margin: 0 }}>{answer}</p>
          {sources.length > 0 && (
            <p className="muted ask-sources">
              From:{" "}
              {sources.map((s, i) => (
                <span key={s.conceptId}>
                  {i > 0 && " · "}
                  <Link href={`/course/${courseId}/c/${s.conceptId}`}>{s.title}</Link>
                </span>
              ))}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
