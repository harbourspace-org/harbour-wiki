import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";

import { DEFAULT_DOMAIN_PROMPT } from "@/lib/domainPrompt";
import { refoldSession, setConfig } from "@/lib/knottra";
import { lectureByNumber, resetLectureNote } from "@/lib/lectures";
import { logUsage } from "@/lib/usage";

// Admin: re-fuse a lecture from its raw events with the CURRENT fusion
// prompt (off-topic guard, study-grade phrasing), replacing the stored notes.
// Knottra's worker rebuilds asynchronously; the emptied wiki note re-syncs on
// read as the new projection lands, and the narrative/quiz self-heal after.

const bodySchema = z.object({
  course: z.string().min(1).max(256),
  lecture: z.number().int().min(1),
  key: z.string().min(1),
});

export async function POST(req: NextRequest) {
  const parsed = bodySchema.safeParse(await req.json().catch(() => null));
  if (!parsed.success) {
    return NextResponse.json({ error: "Invalid body" }, { status: 400 });
  }
  const { course, lecture, key } = parsed.data;
  const token = process.env.MCP_BEARER_TOKEN;
  if (!token || key !== token) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const row = await lectureByNumber(course, lecture);
  if (!row) return NextResponse.json({ error: "Unknown lecture" }, { status: 404 });

  try {
    // The session's stored fusion config is whatever was current when the
    // lecture was RECORDED — push the current prompt first, otherwise the
    // refold would faithfully reproduce the old prompt's flaws.
    await setConfig(row.session_id, DEFAULT_DOMAIN_PROMPT);
    await refoldSession(row.session_id); // enqueue BEFORE emptying our copy
    await resetLectureNote(row.session_id);
    logUsage("web", "lecture_refold", course, { lecture });
    return NextResponse.json({
      status: "refold enqueued",
      session: row.session_id,
      note: "concepts repopulate as the worker re-fuses; narrative regenerates on view",
    });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
