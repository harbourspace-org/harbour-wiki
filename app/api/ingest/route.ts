import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";

import { flush, ingest, setConfig } from "@/lib/knottra";

// Single gateway to Knottra for capture clients. The recorder never holds the
// Knottra API key — it authenticates to Harbour.Wiki with CAPTURE_TOKEN, and
// this route forwards to Knottra using the app's own server-side key. Because
// every write goes through the app's one key, the session is always owned by
// (and readable by) Harbour.Wiki — no per-key tenancy mismatch.

const eventSchema = z.object({
  timestamp: z.string().min(1),
  modality: z.string().min(1).max(64),
  content: z.string().min(1).max(32_000),
  confidence: z.number().min(0).max(1),
});

const bodySchema = z.object({
  session: z.string().min(1).max(256),
  domainPrompt: z.string().max(8000).optional(),
  events: z.array(eventSchema).max(500).optional(),
  flush: z.boolean().optional(),
});

function authorized(req: NextRequest): boolean {
  const token = process.env.CAPTURE_TOKEN;
  // Enforced only when configured (like the MCP endpoint); set it in prod.
  if (!token) return true;
  return req.headers.get("authorization") === `Bearer ${token}`;
}

export async function POST(req: NextRequest) {
  if (!authorized(req)) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const parsed = bodySchema.safeParse(await req.json().catch(() => null));
  if (!parsed.success) {
    return NextResponse.json({ error: "Invalid body", issues: parsed.error.issues }, { status: 400 });
  }
  const { session, domainPrompt, events, flush: doFlush } = parsed.data;

  try {
    // Order matters: config claims/creates the session, then events, then flush.
    if (domainPrompt !== undefined) await setConfig(session, domainPrompt);
    if (events && events.length > 0) await ingest(session, events);
    if (doFlush) await flush(session);

    return NextResponse.json({
      status: "ok",
      session,
      configured: domainPrompt !== undefined,
      ingested: events?.length ?? 0,
      flushed: Boolean(doFlush),
    });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
