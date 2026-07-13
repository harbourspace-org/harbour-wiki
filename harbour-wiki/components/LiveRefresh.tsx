"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";

// While a lecture is LIVE, keep the server-rendered course page fresh without
// the student pressing F5: poll a cheap fingerprint and re-render on change.
// The server component mounts this only when something is actually live, so
// finished courses cost nothing.

const POLL_MS = 15_000;

interface LiveRefreshProps {
  courseId: string;
}

export function LiveRefresh({ courseId }: LiveRefreshProps) {
  const router = useRouter();
  const last = useRef<string | null>(null);

  useEffect(() => {
    let stopped = false;
    const tick = async () => {
      try {
        const r = await fetch(`/api/course-pulse?course=${encodeURIComponent(courseId)}`, {
          cache: "no-store",
        });
        if (!r.ok) return;
        const { fingerprint } = await r.json();
        if (stopped || typeof fingerprint !== "string") return;
        if (last.current !== null && fingerprint !== last.current) router.refresh();
        last.current = fingerprint;
      } catch {
        // network blip — try again next tick
      }
    };
    void tick();
    const id = setInterval(tick, POLL_MS);
    return () => {
      stopped = true;
      clearInterval(id);
    };
  }, [courseId, router]);

  return null;
}
