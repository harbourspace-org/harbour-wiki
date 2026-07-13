import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";

import { q } from "@/lib/db";
import { logUsage } from "@/lib/usage";

// Moderation: remove a concept (and links touching it) from the wiki store —
// for off-topic/private material the always-on mic inevitably picks up.
// Admin-key-gated (MCP_BEARER_TOKEN). Knottra's raw events are untouched; the
// concept disappears from every surface (web + MCP read the wiki store), but
// a full /refold would re-derive it — acceptable for moderation v1.

const bodySchema = z.object({
  course: z.string().min(1).max(256),
  conceptId: z.string().min(1).max(128),
  key: z.string().min(1),
});

export async function POST(req: NextRequest) {
  const parsed = bodySchema.safeParse(await req.json().catch(() => null));
  if (!parsed.success) {
    return NextResponse.json({ error: "Invalid body" }, { status: 400 });
  }
  const { course, conceptId, key } = parsed.data;
  const token = process.env.MCP_BEARER_TOKEN;
  if (!token || key !== token) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    // Strip the concept and any links touching it from every lecture of the
    // course; clear the narrative of affected lectures so it regenerates
    // without the deleted material.
    const rows = await q<{ session_id: string }>(
      `UPDATE harbour_wiki.lecture_note
       SET concepts = concepts - $2,
           links = (
             SELECT COALESCE(jsonb_object_agg(k, v), '{}'::jsonb)
             FROM jsonb_each(links) AS e(k, v)
             WHERE v->>'from_concept' <> $2 AND v->>'to_concept' <> $2
           ),
           narrative = NULL,
           narrative_cursor = 0
       WHERE course_id = $1 AND concepts ? $2
       RETURNING session_id`,
      [course, conceptId],
    );
    if (rows.length === 0) {
      return NextResponse.json({ error: "Concept not found in this course" }, { status: 404 });
    }
    logUsage("web", "concept_delete", course, { conceptId });
    return NextResponse.json({ status: "ok", lectures: rows.map((r) => r.session_id) });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
