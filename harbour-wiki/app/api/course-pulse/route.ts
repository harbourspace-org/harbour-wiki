import { NextRequest, NextResponse } from "next/server";

import { q } from "@/lib/db";

// Cheap liveness pulse for the course page's auto-refresh: one small SQL
// read, no Knottra calls, no LLM. The client re-renders the page only when
// this fingerprint changes.

export async function GET(req: NextRequest) {
  const course = req.nextUrl.searchParams.get("course");
  if (!course) return NextResponse.json({ error: "course is required" }, { status: 400 });
  try {
    const rows = await q<{ fingerprint: string | null }>(
      `SELECT md5(
         COALESCE(string_agg(
           cs.session_id || ':' || COALESCE(n.cursor, 0) || ':' ||
           COALESCE(to_char(cs.finalized_at, 'YYYYMMDDHH24MISS'), 'live') || ':' ||
           (cs.last_seen_at > now() - interval '60 seconds')::text,
           ',' ORDER BY cs.position
         ), '')
       ) AS fingerprint
       FROM harbour_wiki.course_session cs
       LEFT JOIN harbour_wiki.lecture_note n ON n.session_id = cs.session_id
       WHERE cs.course_id = $1`,
      [course],
    );
    return NextResponse.json({ fingerprint: rows[0]?.fingerprint ?? "" });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
