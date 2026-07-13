// Server-side Knottra client. The API key lives only here (never in the browser).

import type { EventIn, RecordOut, SearchOut } from "./types";

const BASE = process.env.KNOTTRA_BASE_URL ?? "http://localhost:8000";
const KEY = process.env.KNOTTRA_API_KEY ?? "dev-key-change-me";

function headers(): HeadersInit {
  return { "X-API-Key": KEY, "Content-Type": "application/json" };
}

async function req(path: string, init?: RequestInit): Promise<Response> {
  return fetch(`${BASE}${path}`, { ...init, headers: headers(), cache: "no-store" });
}

export async function getRecord(session: string, since = 0): Promise<RecordOut | null> {
  const r = await req(`/v1/sessions/${encodeURIComponent(session)}/record?since=${since}`);
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`Knottra record ${r.status}`);
  return r.json();
}

export async function searchRecord(session: string, q: string, k = 8): Promise<SearchOut | null> {
  const r = await req(
    `/v1/sessions/${encodeURIComponent(session)}/record/search?q=${encodeURIComponent(q)}&k=${k}`,
  );
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`Knottra search ${r.status}`);
  return r.json();
}

export async function ingest(session: string, events: EventIn[]): Promise<void> {
  const r = await req(`/v1/sessions/${encodeURIComponent(session)}/events`, {
    method: "POST",
    body: JSON.stringify(events),
  });
  if (!r.ok) throw new Error(`Knottra ingest ${r.status}`);
}

export async function setConfig(session: string, domainPrompt: string): Promise<void> {
  const r = await req(`/v1/sessions/${encodeURIComponent(session)}/config`, {
    method: "PUT",
    body: JSON.stringify({ domain_prompt: domainPrompt }),
  });
  if (!r.ok) throw new Error(`Knottra config ${r.status}`);
}

export async function flush(session: string): Promise<void> {
  const r = await req(`/v1/sessions/${encodeURIComponent(session)}/flush`, { method: "POST" });
  if (!r.ok) throw new Error(`Knottra flush ${r.status}`);
}

/** Regenerate the session's projection from raw events with the CURRENT
 * fusion prompt (async — Knottra's worker re-fuses in the background). */
export async function refoldSession(session: string): Promise<void> {
  const r = await req(`/v1/sessions/${encodeURIComponent(session)}/refold`, { method: "POST" });
  if (!r.ok) throw new Error(`Knottra refold ${r.status}`);
}
