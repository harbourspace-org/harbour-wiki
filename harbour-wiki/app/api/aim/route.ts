import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";

import { locateTarget } from "@/lib/aim";

// Aiming gateway for the capture agent: a room screenshot comes in, Claude
// says where the board/screen is (normalized bbox), the agent moves the
// camera and asks again. Read-only w.r.t. lecture data — nothing is ingested.

// Aim shots are small (≤640px q60); this is far above them.
const MAX_IMAGE_B64 = 2_000_000;

const bodySchema = z.object({
  target: z.enum(["board", "slide", "desk"]).default("board"),
  image: z.string().min(100).max(MAX_IMAGE_B64), // base64 JPEG (no data: prefix)
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
  const { target, image } = parsed.data;

  try {
    const result = await locateTarget(image.replace(/^data:image\/\w+;base64,/, ""), target);
    return NextResponse.json({ status: "ok", target, ...result });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
