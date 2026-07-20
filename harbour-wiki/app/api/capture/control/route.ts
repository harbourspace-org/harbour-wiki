import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";

import {
  captureDashboardData,
  captureOperatorAuthorized,
  clearOperatorFailures,
  enqueueCommand,
  noteOperatorFailure,
  operatorKey,
  operatorRateLimited,
} from "@/lib/captureControl";

const commandSchema = z.object({
  agentId: z.string().min(1).max(200),
  kind: z.enum(["stop", "extend", "skip"]),
  minutes: z.number().int().min(1).max(180).optional(),
});

function clientIp(req: NextRequest): string {
  return req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || "unknown";
}

// Shared operator gate: rate-limit by IP, then verify the Bearer key. Returns
// an error response to short-circuit, or null when the caller is authorized.
function guardOperator(req: NextRequest): NextResponse | null {
  const ip = clientIp(req);
  if (operatorRateLimited(ip, Date.now())) {
    return NextResponse.json({ error: "Too many attempts" }, { status: 429 });
  }
  if (!captureOperatorAuthorized(operatorKey(req.headers.get("authorization")))) {
    noteOperatorFailure(ip, Date.now());
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  clearOperatorFailures(ip);
  return null;
}

export async function GET(req: NextRequest) {
  const denied = guardOperator(req);
  if (denied) return denied;
  try {
    return NextResponse.json(await captureDashboardData());
  } catch (error) {
    return NextResponse.json({ error: String(error) }, { status: 502 });
  }
}

export async function POST(req: NextRequest) {
  const denied = guardOperator(req);
  if (denied) return denied;
  const parsed = commandSchema.safeParse(await req.json().catch(() => null));
  if (!parsed.success) {
    return NextResponse.json(
      { error: "Invalid body", issues: parsed.error.issues },
      { status: 400 },
    );
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
