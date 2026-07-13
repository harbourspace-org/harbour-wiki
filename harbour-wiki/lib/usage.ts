// Usage/feedback logging — fire-and-forget: instrumentation must never slow
// down or break the surface it measures.

import { q } from "./db";

export type Surface = "mcp" | "web" | "ask" | "feedback";

export function logUsage(
  surface: Surface,
  name: string,
  course?: string | null,
  meta?: Record<string, unknown>,
): void {
  void q(
    `INSERT INTO harbour_wiki.usage_event (surface, name, course, meta)
     VALUES ($1, $2, $3, $4)`,
    [surface, name, course ?? null, meta ? JSON.stringify(meta) : null],
  ).catch(() => undefined);
}

export type UsageSummary = {
  since: string;
  totals: { surface: string; name: string; count: number }[];
  byDay: { day: string; surface: string; count: number }[];
  votes: { vote: string; count: number }[];
};

export async function usageSummary(days = 14): Promise<UsageSummary> {
  const totals = await q<{ surface: string; name: string; count: number }>(
    `SELECT surface, name, count(*)::int AS count FROM harbour_wiki.usage_event
     WHERE at > now() - $1::int * interval '1 day'
     GROUP BY surface, name ORDER BY count DESC`,
    [days],
  );
  const byDay = await q<{ day: string; surface: string; count: number }>(
    `SELECT to_char(at::date, 'YYYY-MM-DD') AS day, surface, count(*)::int AS count
     FROM harbour_wiki.usage_event
     WHERE at > now() - $1::int * interval '1 day'
     GROUP BY 1, 2 ORDER BY 1 DESC, 3 DESC`,
    [days],
  );
  const votes = await q<{ vote: string; count: number }>(
    `SELECT meta->>'vote' AS vote, count(*)::int AS count FROM harbour_wiki.usage_event
     WHERE surface = 'feedback' AND at > now() - $1::int * interval '1 day'
     GROUP BY 1`,
    [days],
  );
  return { since: `${days}d`, totals, byDay, votes };
}
