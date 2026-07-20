import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";

import {
  captureOperatorAuthorized,
  getScheduleForAgent,
  putSchedule,
} from "@/lib/captureControl";

// The lecture PC (agent) pulls its timetable here with CAPTURE_TOKEN; the
// operator uploads a timetable from their laptop with CAPTURE_DASHBOARD_TOKEN.
// Full schedule validation happens on the capture side — here we only sanity
// check the envelope so obvious garbage never reaches an agent.
// A modest classroom PC re-parses/validates this on every poll, so cap it.
const MAX_SCHEDULE_BYTES = 256_000;
const agentIdSchema = z
  .string()
  .min(1)
  .max(200)
  .regex(/^[A-Za-z0-9._-]+$/, "agentId may only contain letters, digits, . _ -");

const scheduleBodySchema = z
  .object({
    start_date: z.string().min(1).max(40),
    lessons: z.array(z.record(z.string(), z.unknown())).min(1).max(500),
  })
  .passthrough();

const uploadSchema = z.object({
  key: z.string().min(1),
  agentId: agentIdSchema,
  schedule: scheduleBodySchema,
});

function agentAuthorized(req: NextRequest): boolean {
  const token = process.env.CAPTURE_TOKEN;
  if (!token) return process.env.NODE_ENV !== "production";
  return req.headers.get("authorization") === `Bearer ${token}`;
}

// Agent: fetch this machine's timetable, but only when it changed.
export async function GET(req: NextRequest) {
  if (!agentAuthorized(req)) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const agentId = req.nextUrl.searchParams.get("agentId");
  if (!agentId || !agentIdSchema.safeParse(agentId).success) {
    return NextResponse.json({ error: "valid agentId required" }, { status: 400 });
  }
  const known = req.nextUrl.searchParams.get("version");
  try {
    const row = await getScheduleForAgent(agentId);
    if (!row || row.version === known) {
      return NextResponse.json({ status: "ok", changed: false });
    }
    return NextResponse.json({
      status: "ok",
      changed: true,
      schedule: row.body,
      version: row.version,
    });
  } catch (error) {
    return NextResponse.json({ error: String(error) }, { status: 502 });
  }
}

// Operator: upload/replace a machine's timetable from the dashboard/laptop.
export async function POST(req: NextRequest) {
  const declared = Number(req.headers.get("content-length") ?? 0);
  if (declared > MAX_SCHEDULE_BYTES) {
    return NextResponse.json({ error: "Schedule too large" }, { status: 413 });
  }
  const parsed = uploadSchema.safeParse(await req.json().catch(() => null));
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
    const { version } = await putSchedule(parsed.data.agentId, parsed.data.schedule);
    return NextResponse.json({ status: "saved", version });
  } catch (error) {
    return NextResponse.json({ error: String(error) }, { status: 502 });
  }
}
