import { NextRequest, NextResponse } from "next/server";

import { usageSummary } from "@/lib/usage";

// Tech-Team-only usage summary for the feedback experiment.
// GET /api/stats?key=<MCP_BEARER_TOKEN>&days=14

export async function GET(req: NextRequest) {
  const token = process.env.MCP_BEARER_TOKEN;
  const key = req.nextUrl.searchParams.get("key");
  if (!token || key !== token) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const days = Math.min(90, Math.max(1, Number(req.nextUrl.searchParams.get("days") ?? 14)));
  try {
    return NextResponse.json(await usageSummary(days));
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
