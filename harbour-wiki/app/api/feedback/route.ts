import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";

import { runWithRequest } from "@/lib/requestContext";
import { logUsage } from "@/lib/usage";

const bodySchema = z.object({
  course: z.string().min(1).max(256),
  lecture: z.number().int().optional(),
  vote: z.enum(["up", "down"]),
  comment: z.string().max(2000).optional(),
});

export async function POST(req: NextRequest) {
  return runWithRequest(req, () => handle(req));
}

async function handle(req: NextRequest) {
  const parsed = bodySchema.safeParse(await req.json().catch(() => null));
  if (!parsed.success) {
    return NextResponse.json({ error: "Invalid body" }, { status: 400 });
  }
  const { course, lecture, vote, comment } = parsed.data;
  logUsage("feedback", "vote", course, { lecture, vote, comment });
  return NextResponse.json({ status: "ok" });
}
