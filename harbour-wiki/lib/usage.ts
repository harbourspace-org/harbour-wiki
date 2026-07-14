// Usage/feedback logging — fire-and-forget: instrumentation must never slow
// down or break the surface it measures.

import { q } from "./db";
import { currentUserHash } from "./requestContext";

export type Surface = "mcp" | "web" | "ask" | "feedback";

export function logUsage(
  surface: Surface,
  name: string,
  course?: string | null,
  meta?: Record<string, unknown>,
): void {
  // `u` = salted IP hash (distinct-user proxy), picked up automatically when
  // the call happens inside runWithRequest().
  const u = currentUserHash();
  const merged = { ...(meta ?? {}), ...(u ? { u } : {}) };
  void q(
    `INSERT INTO harbour_wiki.usage_event (surface, name, course, meta)
     VALUES ($1, $2, $3, $4)`,
    [surface, name, course ?? null, Object.keys(merged).length ? JSON.stringify(merged) : null],
  ).catch(() => undefined);
}

export type UsageSummary = {
  since: string;
  totals: { surface: string; name: string; count: number }[];
  byDay: { day: string; surface: string; count: number }[];
  votes: { vote: string; count: number }[];
  /** Distinct users (salted-IP proxy) per surface. Caveat: claude.ai web
   * connector traffic egresses from Anthropic's servers, so several web
   * students can share a hash — treat as a floor for that share. */
  distinctUsers: { surface: string; users: number }[];
  distinctUsersByDay: { day: string; users: number }[];
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
  const distinctUsers = await q<{ surface: string; users: number }>(
    `SELECT surface, count(DISTINCT meta->>'u')::int AS users
     FROM harbour_wiki.usage_event
     WHERE meta->>'u' IS NOT NULL AND at > now() - $1::int * interval '1 day'
     GROUP BY surface ORDER BY users DESC`,
    [days],
  );
  const distinctUsersByDay = await q<{ day: string; users: number }>(
    `SELECT to_char(at::date, 'YYYY-MM-DD') AS day, count(DISTINCT meta->>'u')::int AS users
     FROM harbour_wiki.usage_event
     WHERE meta->>'u' IS NOT NULL AND at > now() - $1::int * interval '1 day'
     GROUP BY 1 ORDER BY 1 DESC`,
    [days],
  );
  return { since: `${days}d`, totals, byDay, votes, distinctUsers, distinctUsersByDay };
}
