import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";

import {
  acknowledgeCommands,
  pendingCommands,
  recordHeartbeat,
} from "@/lib/captureControl";

const momentSchema = z.object({
  courseId: z.string().min(1).max(200),
  courseName: z.string().min(1).max(256),
  lecture: z.number().int().positive(),
  slot: z.number().int().min(1).max(3),
  startsAt: z.string().datetime({ offset: true }),
  endsAt: z.string().datetime({ offset: true }),
});

const heartbeatSchema = z.object({
  agentId: z.string().min(1).max(200),
  hostname: z.string().min(1).max(256),
  schedulerStatus: z.string().min(1).max(64),
  sessionId: z.string().max(256).nullable().optional(),
  current: momentSchema.nullable().optional(),
  next: momentSchema.nullable().optional(),
  audioStatus: z.string().min(1).max(64),
  cameraStatus: z.string().min(1).max(64),
  zoomStatus: z.string().min(1).max(64),
  outboxPending: z.number().int().nonnegative().max(10_000_000),
  errors: z.array(z.string().max(2000)).max(20).default([]),
  commandResults: z
    .array(
      z.object({
        id: z.number().int().positive(),
        ok: z.boolean(),
        message: z.string().max(2000).optional(),
      }),
    )
    .max(20)
    .default([]),
});

function authorized(req: NextRequest): boolean {
  const token = process.env.CAPTURE_TOKEN;
  if (!token) return process.env.NODE_ENV !== "production";
  return req.headers.get("authorization") === `Bearer ${token}`;
}

export async function POST(req: NextRequest) {
  if (!authorized(req)) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const parsed = heartbeatSchema.safeParse(await req.json().catch(() => null));
  if (!parsed.success) {
    return NextResponse.json(
      { error: "Invalid body", issues: parsed.error.issues },
      { status: 400 },
    );
  }
  try {
    const { commandResults, ...heartbeat } = parsed.data;
    await recordHeartbeat(heartbeat);
    await acknowledgeCommands(commandResults);
    return NextResponse.json({
      status: "ok",
      commands: await pendingCommands(heartbeat.agentId),
      serverTime: new Date().toISOString(),
    });
  } catch (error) {
    return NextResponse.json({ error: String(error) }, { status: 502 });
  }
}
