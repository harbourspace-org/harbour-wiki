import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";

import {
  captureDashboardData,
  captureOperatorAuthorized,
  enqueueCommand,
} from "@/lib/captureControl";

const commandSchema = z.object({
  key: z.string().min(1),
  agentId: z.string().min(1).max(200),
  kind: z.enum(["stop", "extend", "skip"]),
  minutes: z.number().int().min(1).max(180).optional(),
});

export async function GET(req: NextRequest) {
  if (!captureOperatorAuthorized(req.nextUrl.searchParams.get("key"))) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  try {
    return NextResponse.json(await captureDashboardData());
  } catch (error) {
    return NextResponse.json({ error: String(error) }, { status: 502 });
  }
}

export async function POST(req: NextRequest) {
  const parsed = commandSchema.safeParse(await req.json().catch(() => null));
  if (!parsed.success) {
    return NextResponse.json(
      { error: "Invalid body", issues: parsed.error.issues },
      { status: 400 },
    );
  }
  if (!captureOperatorAuthorized(parsed.data.key)) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  try {
    const payload =
      parsed.data.kind === "extend" ? { minutes: parsed.data.minutes ?? 15 } : {};
    return NextResponse.json({
      status: "queued",
      command: await enqueueCommand(parsed.data.agentId, parsed.data.kind, payload),
    });
  } catch (error) {
    return NextResponse.json({ error: String(error) }, { status: 502 });
  }
}
