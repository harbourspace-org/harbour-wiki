import { NextRequest, NextResponse } from "next/server";

import { courseSessions } from "@/lib/courses";
import { searchRecord } from "@/lib/knottra";

// Course-wide search: query each lecture's Knottra index, merge by score.
export async function GET(req: NextRequest) {
  const course = req.nextUrl.searchParams.get("course");
  const qstr = req.nextUrl.searchParams.get("q");
  if (!course || !qstr) {
    return NextResponse.json({ error: "course and q are required" }, { status: 400 });
  }
  try {
    const sessions = await courseSessions(course);
    const perSession = await Promise.all(
      sessions.map(async (s) => {
        const r = await searchRecord(s.session_id, qstr, 5).catch(() => null);
        return (r?.hits ?? []).map((h) => ({
          conceptId: h.concept.id,
          title: h.concept.title,
          score: h.score,
          lecture: s.label || s.session_id,
        }));
      }),
    );
    const hits = perSession.flat().sort((a, b) => b.score - a.score).slice(0, 12);
    return NextResponse.json({ hits });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
