import { NextResponse } from "next/server";

import { addCourseSession, upsertCourse } from "@/lib/courses";
import { flush, getRecord, ingest, setConfig } from "@/lib/knottra";
import { SAMPLE_DOMAIN, SAMPLE_EVENTS } from "@/lib/sample";

const COURSE_ID = "cs-derivatives";
const SESSION = "demo";

// Demo: create a course pointing at the sample lecture. If that session hasn't
// been fused yet, ingest + flush it (requires the Knottra worker running).
export async function POST() {
  try {
    const existing = await getRecord(SESSION);
    if (!existing || existing.concepts.length === 0) {
      await setConfig(SESSION, SAMPLE_DOMAIN);
      await ingest(SESSION, SAMPLE_EVENTS);
      await flush(SESSION);
    }
    await upsertCourse(COURSE_ID, "Calculus — Derivatives", SAMPLE_DOMAIN);
    await addCourseSession(COURSE_ID, SESSION, 0, "Lecture 4 — Derivatives");
    return NextResponse.json({ status: "seeded", course: COURSE_ID });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
