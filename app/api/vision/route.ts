import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";

import { ingest } from "@/lib/knottra";
import { extractFrameText } from "@/lib/vision";

// Camera-agent gateway: a lecture frame comes in, the server-side vision LLM
// extracts its text, and the result is ingested into the SAME session the
// audio recorder feeds — Knottra fuses speech + board into one record. The
// lecture PC never holds the LLM key (same single-gateway rule as /api/ingest).

// ~6 MB of base64 ≈ a 4.5 MB JPEG — far above the agent's 1280px q70 frames.
const MAX_IMAGE_B64 = 6_000_000;

const bodySchema = z.object({
  session: z.string().min(1).max(256),
  modality: z.enum(["board", "slide", "desk"]).default("board"),
  image: z.string().min(100).max(MAX_IMAGE_B64), // base64 JPEG (no data: prefix)
  timestamp: z.string().min(1).optional(),
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
  const { session, modality, image, timestamp } = parsed.data;

  try {
    const extraction = await extractFrameText(image.replace(/^data:image\/\w+;base64,/, ""), modality);
    if (!extraction) {
      return NextResponse.json({ status: "ok", extracted: false, ingested: 0 });
    }
    await ingest(session, [
      {
        timestamp: timestamp ?? new Date().toISOString(),
        modality,
        content: extraction.text,
        confidence: extraction.confidence,
      },
    ]);
    return NextResponse.json({
      status: "ok",
      extracted: true,
      ingested: 1,
      modality,
      chars: extraction.text.length,
    });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
