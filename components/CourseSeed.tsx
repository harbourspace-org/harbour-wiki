"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function CourseSeed() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  async function seed() {
    setBusy(true);
    try {
      const r = await fetch("/api/course/seed", { method: "POST" });
      const data = await r.json();
      if (!r.ok) {
        alert(`Seed failed: ${data.error ?? r.status}. Is the Knottra API (+ worker) running?`);
        return;
      }
      await new Promise((res) => setTimeout(res, 1500));
      router.push(`/course/${data.course}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <button className="btn" onClick={seed} disabled={busy}>
      {busy ? "Seeding…" : "Seed demo course"}
    </button>
  );
}
