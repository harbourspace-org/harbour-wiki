import { NextRequest, NextResponse } from "next/server";

import { courseSessions } from "@/lib/courses";
import { searchRecord } from "@/lib/knottra";
import { groundedAnswer } from "@/lib/llm";
import type { SearchHit } from "@/lib/types";
import { logUsage } from "@/lib/usage";

// Grounded Q&A. Two scopes:
//   { session, question } — one lecture (the original shape)
//   { course, question }  — the whole course (used by the on-page Ask box,
//     so students without a paid Claude plan get the same capability).

export async function POST(req: NextRequest) {
  const { session, course, question } = await req.json().catch(() => ({}));
  if (!question || (!session && !course)) {
    return NextResponse.json(
      { error: "question plus session or course are required" },
      { status: 400 },
    );
  }
  try {
    let hits: SearchHit[] = [];
    const lectureOf = new Map<string, string>();
    if (session) {
      const result = await searchRecord(session, question, 6);
      if (result === null) return NextResponse.json({ error: "Unknown session" }, { status: 404 });
      hits = result.hits;
    } else {
      const sessions = await courseSessions(course);
      if (sessions.length === 0) {
        return NextResponse.json({ error: "Unknown or empty course" }, { status: 404 });
      }
      const per = await Promise.all(
        sessions.map(async (s) => {
          const r = await searchRecord(s.session_id, question, 4).catch(() => null);
          return (r?.hits ?? []).map((h) => {
            lectureOf.set(h.concept.id, s.label || s.session_id);
            return h;
          });
        }),
      );
      hits = per
        .flat()
        .sort((a, b) => b.score - a.score)
        .slice(0, 6);
    }

    const answer = await groundedAnswer(question, hits);
    logUsage("ask", "ask", course ?? null, { session, chars: question.length });
    return NextResponse.json({
      answer,
      sources: hits.map((h) => ({
        conceptId: h.concept.id,
        title: h.concept.title,
        lecture: lectureOf.get(h.concept.id) ?? null,
      })),
      hits, // kept for the original session-scoped consumers
    });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
