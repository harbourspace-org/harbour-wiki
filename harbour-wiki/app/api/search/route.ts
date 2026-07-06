import { NextRequest, NextResponse } from "next/server";

import { searchRecord } from "@/lib/knottra";

export async function GET(req: NextRequest) {
  const session = req.nextUrl.searchParams.get("session");
  const q = req.nextUrl.searchParams.get("q");
  if (!session || !q) {
    return NextResponse.json({ error: "session and q are required" }, { status: 400 });
  }
  try {
    const result = await searchRecord(session, q, 8);
    if (result === null) return NextResponse.json({ error: "Unknown session" }, { status: 404 });
    return NextResponse.json(result);
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
