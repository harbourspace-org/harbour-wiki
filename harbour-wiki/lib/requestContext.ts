// Per-request context so deeply nested code (MCP tool handlers) can attach
// the caller's identity proxy to usage logs without threading the request
// through every layer. Node runtime only (AsyncLocalStorage).

import { createHash } from "node:crypto";
import { AsyncLocalStorage } from "node:async_hooks";

type RequestContext = { userHash: string };

const als = new AsyncLocalStorage<RequestContext>();

/** Short salted hash of the client IP — a distinct-user proxy, not an identity.
 * Salted so raw IPs never land in the database. */
export function userHashFrom(req: Request): string {
  const ip =
    req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ||
    req.headers.get("x-real-ip") ||
    "unknown";
  const salt = process.env.MCP_BEARER_TOKEN ?? "hw";
  return createHash("sha1").update(`${salt}:${ip}`).digest("hex").slice(0, 12);
}

export function runWithRequest<T>(req: Request, fn: () => T): T {
  return als.run({ userHash: userHashFrom(req) }, fn);
}

export function currentUserHash(): string | null {
  return als.getStore()?.userHash ?? null;
}
