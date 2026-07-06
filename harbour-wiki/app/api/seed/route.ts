import { NextRequest, NextResponse } from "next/server";

import { flush, ingest, setConfig } from "@/lib/knottra";
import { SAMPLE_DOMAIN, SAMPLE_EVENTS } from "@/lib/sample";

// Demo helper: populate a session with a sample lecture, then flush so the
// worker fuses it. Requires the Knottra API + worker to be running.
export async function POST(req: NextRequest) {
  const { session } = await req.json().catch(() => ({}));
  const sid = session || "demo";
  try {
    await setConfig(sid, SAMPLE_DOMAIN);
    await ingest(sid, SAMPLE_EVENTS);
    await flush(sid);
    return NextResponse.json({ status: "seeded", session: sid, events: SAMPLE_EVENTS.length });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
