"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function SessionEntry() {
  const router = useRouter();
  const [session, setSession] = useState("demo");
  const [seeding, setSeeding] = useState(false);

  function open() {
    if (session.trim()) router.push(`/wiki/${encodeURIComponent(session.trim())}`);
  }

  async function seed() {
    setSeeding(true);
    try {
      const r = await fetch("/api/seed", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session: session.trim() || "demo" }),
      });
      if (!r.ok) {
        const e = await r.json().catch(() => ({}));
        alert(`Seed failed: ${e.error ?? r.status}. Is the Knottra API + worker running?`);
        return;
      }
      // Give the worker a moment to fuse, then open.
      await new Promise((res) => setTimeout(res, 4000));
      router.push(`/wiki/${encodeURIComponent(session.trim() || "demo")}`);
    } finally {
      setSeeding(false);
    }
  }

  return (
    <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap", marginTop: "2rem" }}>
      <input
        className="field"
        style={{ maxWidth: "20rem" }}
        value={session}
        onChange={(e) => setSession(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && open()}
        placeholder="session id (e.g. lecture-04)"
        aria-label="Session id"
      />
      <button className="btn" onClick={open}>
        Open compendium
      </button>
      <button className="btn" onClick={seed} disabled={seeding} style={{ background: "transparent", color: "var(--accent)", borderColor: "var(--accent)" }}>
        {seeding ? "Seeding…" : "Seed demo lecture"}
      </button>
    </div>
  );
}
