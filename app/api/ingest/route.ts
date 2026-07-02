import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";

import { upsertCourse } from "@/lib/courses";
import { flush, ingest, setConfig } from "@/lib/knottra";
import { finalizeLecture, startLecture, syncLectureNote } from "@/lib/lectures";

// Single gateway to Knottra for capture clients. The recorder never holds the
// Knottra API key — it authenticates here with CAPTURE_TOKEN and announces
// only "class X is recording now"; THIS route decides which lecture that is
// (resume-or-create, auto-numbered), which Knottra session backs it, and
// where the notes live.

const DEFAULT_DOMAIN_PROMPT =
  "This is a university lecture. Group the speech into the concepts being " +
  "taught, each with its sub-points and the logical flow between concepts.";

const eventSchema = z.object({
  timestamp: z.string().min(1),
  modality: z.string().min(1).max(64),
  content: z.string().min(1).max(32_000),
  confidence: z.number().min(0).max(1),
});

// start: begin (or resume) the current lecture of a class.
const startSchema = z.object({
  action: z.literal("start"),
  course: z.object({
    id: z.string().min(1).max(200),
    title: z.string().min(1).max(256).optional(),
  }),
  lectureTitle: z.string().min(1).max(256).optional(),
  domainPrompt: z.string().max(8000).optional(),
  forceNew: z.boolean().optional(),
});

// stream/flush: session-addressed (the session came from `start`).
const streamSchema = z.object({
  action: z.undefined().optional(),
  session: z.string().min(1).max(256),
  courseId: z.string().min(1).max(200).optional(),
  events: z.array(eventSchema).max(500).optional(),
  flush: z.boolean().optional(),
});

function authorized(req: NextRequest): boolean {
  const token = process.env.CAPTURE_TOKEN;
  if (!token) return true; // open only when unconfigured (local dev)
  return req.headers.get("authorization") === `Bearer ${token}`;
}

export async function POST(req: NextRequest) {
  if (!authorized(req)) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const body = await req.json().catch(() => null);

  try {
    if (body?.action === "start") {
      const parsed = startSchema.safeParse(body);
      if (!parsed.success) {
        return NextResponse.json(
          { error: "Invalid body", issues: parsed.error.issues },
          { status: 400 },
        );
      }
      const { course, lectureTitle, domainPrompt, forceNew } = parsed.data;
      const prompt = domainPrompt ?? DEFAULT_DOMAIN_PROMPT;
      await upsertCourse(course.id, course.title, prompt);
      const started = await startLecture(course.id, lectureTitle, forceNew);
      await setConfig(started.session, prompt);
      return NextResponse.json({
        status: "ok",
        course: course.id,
        session: started.session,
        lecture: started.lecture,
        resumed: started.resumed,
      });
    }

    const parsed = streamSchema.safeParse(body);
    if (!parsed.success) {
      return NextResponse.json(
        { error: "Invalid body", issues: parsed.error.issues },
        { status: 400 },
      );
    }
    const { session, events, flush: doFlush } = parsed.data;
    // Session ids are gateway-derived: "<courseId>--lNN".
    const courseId = parsed.data.courseId ?? session.split("--l")[0];

    if (events && events.length > 0) await ingest(session, events);
    if (doFlush) {
      await flush(session);
      await finalizeLecture(session);
      // Pull whatever is already fused; sync-on-read covers the trailing fold.
      await syncLectureNote(courseId, session).catch(() => null);
    }

    return NextResponse.json({
      status: "ok",
      session,
      ingested: events?.length ?? 0,
      flushed: Boolean(doFlush),
    });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
