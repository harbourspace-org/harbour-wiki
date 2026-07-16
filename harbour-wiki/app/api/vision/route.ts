import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";

import { ingest } from "@/lib/knottra";

// Camera-agent gateway: a lecture frame comes in and is forwarded, AS AN
// IMAGE, into the SAME session the audio recorder feeds — Knottra's fusion
// model reads the photo directly (alongside concurrent speech) rather than
// this app pre-extracting its text. The lecture PC never holds the Knottra
// key (same single-gateway rule as /api/ingest).

// ~6 MB of base64 ≈ a 4.5 MB JPEG — far above the agent's 1280px q70 frames.
const MAX_IMAGE_B64 = 6_000_000;

// Capture-quality confidence (this camera frame is trustworthy input), not a
// text-extraction confidence — Knottra's fuser does the reading now.
const CAPTURE_CONFIDENCE: Record<string, number> = { board: 0.8, slide: 0.8, desk: 0.6 };

const bodySchema = z.object({
  session: z.string().min(1).max(256),
  modality: z.enum(["board", "slide", "desk"]).default("board"),
  image: z.string().min(100).max(MAX_IMAGE_B64), // base64 JPEG (no data: prefix)
  timestamp: z.string().min(1).optional(),
  clientEventId: z.string().min(8).max(128).optional(),
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
  const parsed = bodySchema.safeParse(await req.json().catch(() => null));
  if (!parsed.success) {
    return NextResponse.json(
      { error: "Invalid body", issues: parsed.error.issues },
      { status: 400 },
    );
  }
  const { session, modality, image, timestamp, clientEventId } = parsed.data;
  const imageB64 = image.replace(/^data:image\/\w+;base64,/, "");

  try {
    await ingest(session, [
      {
        client_event_id: clientEventId,
        timestamp: timestamp ?? new Date().toISOString(),
        modality,
        content: "",
        image_b64: imageB64,
        confidence: CAPTURE_CONFIDENCE[modality] ?? 0.7,
      },
    ]);
    return NextResponse.json({ status: "ok", ingested: 1, modality });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
