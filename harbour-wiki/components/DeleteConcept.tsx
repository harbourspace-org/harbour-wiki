"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

// Moderation: remove an off-topic/private concept from the wiki store.
// Requires the admin key (asked once, kept in localStorage) — students see
// the button but can't delete without it.

interface DeleteConceptProps {
  courseId: string;
  conceptId: string;
}

export function DeleteConcept({ courseId, conceptId }: DeleteConceptProps) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  async function remove() {
    const key =
      localStorage.getItem("hw_admin_key") ||
      window.prompt("Admin key (Tech Team only):") ||
      "";
    if (!key) return;
    if (!window.confirm("Delete this concept from the wiki? This cannot be undone.")) return;
    setBusy(true);
    try {
      const r = await fetch("/api/concept/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ course: courseId, conceptId, key }),
      });
      if (r.status === 401) {
        localStorage.removeItem("hw_admin_key");
        alert("Wrong admin key.");
        return;
      }
      if (!r.ok) {
        alert(`Delete failed (${r.status})`);
        return;
      }
      localStorage.setItem("hw_admin_key", key);
      router.push(`/course/${courseId}`);
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  return (
    <button className="delete-concept" onClick={remove} disabled={busy}>
      {busy ? "deleting…" : "delete concept (admin)"}
    </button>
  );
}
