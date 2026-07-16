import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";

import { correctTranscript } from "@/lib/correct";
import { upsertCourse } from "@/lib/courses";
import { flush, ingest, setConfig } from "@/lib/knottra";
import {
  courseVocabulary,
  finalizeLecture,
  startLecture,
  syncLectureNote,
  touchLecture,
} from "@/lib/lectures";

// Single gateway to Knottra for capture clients. The recorder never holds the
// Knottra API key — it authenticates here with CAPTURE_TOKEN and announces
// only "class X is recording now"; THIS route decides which lecture that is
// (resume-or-create, auto-numbered), which Knottra session backs it, and
// where the notes live.

import { DEFAULT_DOMAIN_PROMPT } from "@/lib/domainPrompt";

const eventSchema = z.object({
  client_event_id: z.string().min(8).max(128).optional(),
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
  // Mid-run vocabulary refresh: answer with the current lecture + vocabulary,
  // but never create or reconfigure anything.
  refreshOnly: z.boolean().optional(),
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
      const { course, lectureTitle, domainPrompt, forceNew, refreshOnly } = parsed.data;
      const prompt = domainPrompt ?? DEFAULT_DOMAIN_PROMPT;
      if (!refreshOnly) await upsertCourse(course.id, course.title, prompt);
      const started = await startLecture(course.id, lectureTitle, forceNew, refreshOnly);
      if (!refreshOnly) await setConfig(started.session, prompt);
      return NextResponse.json({
        status: "ok",
        course: course.id,
        session: started.session,
        lecture: started.lecture,
        resumed: started.resumed,
        // The course's known terminology (concept titles from all lectures) —
        // the recorder feeds it to its transcriber as a vocabulary bias, so
        // past lectures teach the STT the course's language.
        vocabulary: await courseVocabulary(course.id),
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

    if (events && events.length > 0) {
      // ASR post-correction: fix mishearings in speech events with a small
      // model + course vocabulary before they reach fusion. Best-effort —
      // failures/timeouts pass the original text through.
      const corrected = await Promise.all(
        events.map(async (ev) =>
          ev.modality === "speech"
            ? { ...ev, content: await correctTranscript(ev.content, courseId) }
            : ev,
        ),
      );
      await ingest(session, corrected);
      // Slide the resume window: the lecture is demonstrably still going.
      await touchLecture(session);
    }
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
