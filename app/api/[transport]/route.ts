import { createMcpHandler } from "mcp-handler";
import { z } from "zod";

import { buildCourseGraph } from "@/lib/aggregate";
import { courseSessions, listCourses } from "@/lib/courses";
import { getRecord, searchRecord } from "@/lib/knottra";

// MCP server: students connect a course/lecture context in Claude.ai and ask
// questions. Tools return Knottra's STRUCTURED slices (data, not answers) —
// Claude.ai composes the grounded answer from them.

const json = (data: unknown) => ({
  content: [{ type: "text" as const, text: JSON.stringify(data, null, 2) }],
});

const handler = createMcpHandler(
  (server) => {
    server.registerTool(
      "list_courses",
      {
        title: "List courses",
        description:
          "List the courses available in Harbour.Wiki. Call this first to find the course id to use as context.",
        inputSchema: {},
      },
      async () => json(await listCourses()),
    );

    server.registerTool(
      "list_lectures",
      {
        title: "List lectures in a course",
        description: "List the lectures (sessions) that make up a course, with concept counts.",
        inputSchema: { course: z.string().describe("Course id from list_courses") },
      },
      async ({ course }) => {
        const graph = await buildCourseGraph(course);
        if (!graph) return json({ error: "Unknown course" });
        return json(
          graph.lectures.map((l) => ({
            session: l.sessionId,
            label: l.label,
            concepts: l.concepts.length,
          })),
        );
      },
    );

    server.registerTool(
      "search_lectures",
      {
        title: "Search the course by meaning",
        description:
          "Semantic search across a course's fused lecture record. Returns the most relevant concepts (title, explanation, sub-points, source lecture). Use these to ground your answer to the student; do not invent facts beyond them.",
        inputSchema: {
          course: z.string().describe("Course id (context to search)"),
          query: z.string().describe("The student's question or topic"),
          k: z.number().int().min(1).max(20).optional().describe("Max results (default 8)"),
        },
      },
      async ({ course, query, k }) => {
        const sessions = await courseSessions(course);
        if (sessions.length === 0) return json({ error: "Unknown or empty course" });
        const per = await Promise.all(
          sessions.map(async (s) => {
            const r = await searchRecord(s.session_id, query, k ?? 8).catch(() => null);
            return (r?.hits ?? []).map((h) => ({
              concept_id: h.concept.id,
              title: h.concept.title,
              detail: h.concept.detail,
              sub_points: h.concept.sub_points.map((sp) => sp.text),
              modalities: h.concept.modalities,
              lecture: s.label || s.session_id,
              score: Number(h.score.toFixed(3)),
            }));
          }),
        );
        const hits = per.flat().sort((a, b) => b.score - a.score).slice(0, k ?? 8);
        return json({ course, query, hits });
      },
    );

    server.registerTool(
      "get_concept",
      {
        title: "Get one concept with its links",
        description:
          "Fetch a single concept's full detail plus its outgoing links and backlinks (what links here).",
        inputSchema: {
          course: z.string(),
          concept_id: z.string().describe("Concept id from search_lectures"),
        },
      },
      async ({ course, concept_id }) => {
        const graph = await buildCourseGraph(course);
        const c = graph?.conceptsById.get(concept_id);
        if (!graph || !c) return json({ error: "Concept not found" });
        const title = (id: string) => graph.conceptsById.get(id)?.title ?? id;
        return json({
          id: c.id,
          title: c.title,
          detail: c.detail,
          sub_points: c.sub_points.map((s) => s.text),
          lecture: c.lecture,
          links: (graph.outgoing.get(c.id) ?? []).map((l) => ({ kind: l.kind, to: title(l.to) })),
          backlinks: (graph.backlinks.get(c.id) ?? []).map((l) => ({
            kind: l.kind,
            from: title(l.from),
          })),
        });
      },
    );

    server.registerTool(
      "get_lecture_record",
      {
        title: "Get a lecture's full record",
        description: "Fetch the whole fused record (all concepts) for one lecture/session.",
        inputSchema: { session: z.string().describe("Session id of the lecture") },
      },
      async ({ session }) => {
        const rec = await getRecord(session);
        if (!rec) return json({ error: "Unknown session" });
        return json({
          session,
          concepts: rec.concepts.map((c) => ({
            id: c.id,
            title: c.title,
            detail: c.detail,
            sub_points: c.sub_points.map((s) => s.text),
            modalities: c.modalities,
          })),
        });
      },
    );
  },
  {},
  { basePath: "/api", maxDuration: 60, verboseLogs: false },
);

// Optional bearer-token gate (enforced only when MCP_BEARER_TOKEN is set).
async function guarded(req: Request): Promise<Response> {
  const token = process.env.MCP_BEARER_TOKEN;
  if (token && req.headers.get("authorization") !== `Bearer ${token}`) {
    return new Response(JSON.stringify({ error: "Unauthorized" }), {
      status: 401,
      headers: { "Content-Type": "application/json", "WWW-Authenticate": "Bearer" },
    });
  }
  return handler(req);
}

export { guarded as GET, guarded as POST, guarded as DELETE };
