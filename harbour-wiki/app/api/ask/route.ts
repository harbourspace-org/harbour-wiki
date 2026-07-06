import { NextRequest, NextResponse } from "next/server";

import { searchRecord } from "@/lib/knottra";
import { groundedAnswer } from "@/lib/llm";

export async function POST(req: NextRequest) {
  const { session, question } = await req.json().catch(() => ({}));
  if (!session || !question) {
    return NextResponse.json({ error: "session and question are required" }, { status: 400 });
  }
  try {
    const result = await searchRecord(session, question, 6);
    if (result === null) return NextResponse.json({ error: "Unknown session" }, { status: 404 });
    const answer = await groundedAnswer(question, result.hits);
    return NextResponse.json({ answer, hits: result.hits });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
