import { createMcpHandler } from "mcp-handler";
import { z } from "zod";

import { buildCourseGraph } from "@/lib/aggregate";
import { listCourses } from "@/lib/courses";
import { getRecord, searchRecord } from "@/lib/knottra";
import {
  courseLectures,
  getLectureNarrative,
  getLectureNote,
  isLive,
  lectureByNumber,
  syncLectureNote,
} from "@/lib/lectures";
import { splitConspect } from "@/lib/narrative";

// MCP server — the PRIMARY student surface. Students address everything by
// (course, lecture number); raw session ids never leak. Tools return the
// STRUCTURED notes (data, not answers) — the client's model (Claude) composes
// the grounded answer. Live lectures are served near-real-time: reads pull the
// wiki store, which re-syncs from Knottra's delta reads while the lecture runs.

const json = (data: unknown) => ({
  content: [{ type: "text" as const, text: JSON.stringify(data, null, 2) }],
});

const conceptView = (c: {
  id: string;
  title: string;
  detail: string | null;
  sub_points: { text: string }[];
  modalities: string[];
  time_start: string;
  time_end: string;
}) => ({
  concept_id: c.id,
  title: c.title,
  detail: c.detail,
  sub_points: c.sub_points.map((sp) => sp.text),
  modalities: c.modalities,
  // Wall-clock span this concept was taught in — lets the client answer
  // "what happened 10 minutes ago?" style questions.
  time_start: c.time_start,
  time_end: c.time_end,
});

type QuizEntry = { lecture: number; n: number; question: string; answer: string };

// Pull every parseable "Check yourself:" quiz item from a lecture's stored
// narrative — one lecture when `lecture` is given, the whole course otherwise.
// Lectures without a narrative or without a quiz block are silently skipped.
async function collectQuiz(
  course: string,
  lecture?: number,
): Promise<{ error: string } | { items: QuizEntry[] }> {
  let rows;
  if (lecture !== undefined) {
    const row = await lectureByNumber(course, lecture);
    if (!row) return { error: "Unknown lecture" };
    rows = [row];
  } else {
    rows = await courseLectures(course);
    if (rows.length === 0) return { error: "Unknown or empty course" };
  }

  const per = await Promise.all(
    rows.map(async (l) => {
      const result = await getLectureNarrative(course, l.session_id).catch(() => null);
      if (!result?.narrative) return [];
      return splitConspect(result.narrative).quiz.map((item, i) => ({
        lecture: l.position,
        n: i + 1,
        question: item.question,
        answer: item.answer,
      }));
    }),
  );
  const items = per.flat();
  if (items.length === 0) {
    return { error: "No quiz available yet — the notes may still be fusing or regenerating" };
  }
  return { items };
}

const handler = createMcpHandler(
  (server) => {
    server.registerTool(
      "list_courses",
      {
        title: "List courses (classes)",
        description:
          "List the courses in Harbour.Wiki with their lecture counts and which lecture is LIVE " +
          "(being taught right now). Call this first to find the course id.",
        inputSchema: {},
      },
      async () => {
        const courses = await listCourses();
        const out = await Promise.all(
          courses.map(async (c) => {
            const lectures = await courseLectures(c.id);
            const live = lectures.find(isLive);
            return {
              course: c.id,
              title: c.title,
              lectures: lectures.length,
              live_lecture: live ? live.position : null,
            };
          }),
        );
        return json(out);
      },
    );

    server.registerTool(
      "list_lectures",
      {
        title: "List a course's lectures",
        description:
          "The lectures of a course in order, with number, title, date, whether it is LIVE, and " +
          "how many concepts its notes hold.",
        inputSchema: { course: z.string().describe("Course id from list_courses") },
      },
      async ({ course }) => {
        const rows = await courseLectures(course);
        if (rows.length === 0) return json({ error: "Unknown or empty course" });
        const out = await Promise.all(
          rows.map(async (l) => {
            const note = await getLectureNote(course, l.session_id).catch(() => null);
            return {
              lecture: l.position,
              title: l.label ?? `Lecture ${l.position}`,
              started_at: l.started_at,
              live: isLive(l),
              concepts: note?.concepts.length ?? 0,
            };
          }),
        );
        return json(out);
      },
    );

    server.registerTool(
      "get_lecture",
      {
        title: "Get a lecture — narrative + structured notes",
        description:
          "The WHOLE lecture context: a timestamped prose narrative of everything taught so far " +
          "(the rewritten conspect), plus the structured concepts (each with its wall-clock time " +
          "span, sub-points, links). For a LIVE lecture this is the near-real-time state. Use the " +
          "narrative for overview/catch-up answers and the concepts + timestamps for precise or " +
          "'what happened at/around time X' questions. Pass `cursor` to get_lecture_updates to " +
          "poll for what comes next.",
        inputSchema: {
          course: z.string(),
          lecture: z.number().int().min(1).describe("Lecture number from list_lectures"),
        },
      },
      async ({ course, lecture }) => {
        const row = await lectureByNumber(course, lecture);
        if (!row) return json({ error: "Unknown lecture" });
        const result = await getLectureNarrative(course, row.session_id);
        if (!result) return json({ error: "No notes yet — nothing fused for this lecture" });
        const { narrative, note } = result;
        return json({
          course,
          lecture,
          title: row.label,
          live: isLive(row),
          started_at: row.started_at,
          cursor: note.cursor,
          narrative: narrative ?? "(narrative not generated yet)",
          concepts: note.concepts.map(conceptView),
          links: note.links.map((l) => ({ from: l.from_concept, to: l.to_concept, kind: l.kind })),
        });
      },
    );

    server.registerTool(
      "get_lecture_updates",
      {
        title: "Get what's new in a lecture (real-time delta)",
        description:
          "Only the concepts/links fused AFTER the given cursor — poll this during a LIVE lecture " +
          "to follow it in real time. Pass the cursor from get_lecture (or the previous call); " +
          "returns the new cursor.",
        inputSchema: {
          course: z.string(),
          lecture: z.number().int().min(1),
          since: z.number().int().min(0).describe("Cursor from get_lecture / previous call"),
        },
      },
      async ({ course, lecture, since }) => {
        const row = await lectureByNumber(course, lecture);
        if (!row) return json({ error: "Unknown lecture" });
        const delta = await getRecord(row.session_id, since);
        if (!delta) return json({ error: "No record for this lecture yet" });
        // Keep the wiki store fresh as a side effect of live polling.
        await syncLectureNote(course, row.session_id).catch(() => null);
        return json({
          course,
          lecture,
          live: isLive(row),
          cursor: delta.fused_through_seq,
          new_concepts: delta.concepts.map(conceptView),
          new_links: delta.links.map((l) => ({
            from: l.from_concept,
            to: l.to_concept,
            kind: l.kind,
          })),
        });
      },
    );

    server.registerTool(
      "search_lecture",
      {
        title: "Search inside one lecture",
        description:
          "Semantic search over a single lecture's notes. Use to ground answers about THIS " +
          "lecture; do not invent facts beyond the returned concepts.",
        inputSchema: {
          course: z.string(),
          lecture: z.number().int().min(1),
          query: z.string().describe("The student's question or topic"),
          k: z.number().int().min(1).max(20).optional(),
        },
      },
      async ({ course, lecture, query, k }) => {
        const row = await lectureByNumber(course, lecture);
        if (!row) return json({ error: "Unknown lecture" });
        const r = await searchRecord(row.session_id, query, k ?? 8);
        if (!r) return json({ error: "No record for this lecture yet" });
        return json({
          course,
          lecture,
          query,
          hits: r.hits.map((h) => ({
            ...conceptView(h.concept),
            score: Number(h.score.toFixed(3)),
          })),
        });
      },
    );

    server.registerTool(
      "search_course",
      {
        title: "Search across all lectures of a course",
        description:
          "Semantic search over EVERY lecture of a course. Use for questions that span the " +
          "whole class ('how does today relate to lecture 2?'). Ground your answer only in the " +
          "returned concepts.",
        inputSchema: {
          course: z.string(),
          query: z.string(),
          k: z.number().int().min(1).max(20).optional(),
        },
      },
      async ({ course, query, k }) => {
        const rows = await courseLectures(course);
        if (rows.length === 0) return json({ error: "Unknown or empty course" });
        const per = await Promise.all(
          rows.map(async (l) => {
            const r = await searchRecord(l.session_id, query, k ?? 8).catch(() => null);
            return (r?.hits ?? []).map((h) => ({
              ...conceptView(h.concept),
              lecture: l.position,
              lecture_title: l.label,
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
          "One concept's full detail plus outgoing links and backlinks (what links here) across " +
          "the whole course — the Wikipedia-style concept page.",
        inputSchema: {
          course: z.string(),
          concept_id: z.string().describe("Concept id from search/get_lecture"),
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
      "get_quiz_questions",
      {
        title: "Quiz questions — active recall (answers withheld)",
        description:
          "Self-check quiz QUESTIONS for one lecture, or the whole course when `lecture` is " +
          "omitted (exam review). Answers are deliberately withheld. Run ACTIVE RECALL: ask the " +
          "student ONE question at a time, wait for their own attempt, and only AFTER they " +
          "attempt it call get_quiz_answers to grade. Never reveal, guess, or look up an answer " +
          "before the student has tried the question.",
        inputSchema: {
          course: z.string().describe("Course id from list_courses"),
          lecture: z
            .number()
            .int()
            .min(1)
            .optional()
            .describe("Lecture number from list_lectures; omit for course-wide review"),
        },
      },
      async ({ course, lecture }) => {
        const res = await collectQuiz(course, lecture);
        if ("error" in res) return json({ error: res.error });
        return json({
          course,
          lecture: lecture ?? "all",
          total: res.items.length,
          questions: res.items.map((it) => ({
            lecture: it.lecture,
            n: it.n,
            question: it.question,
          })),
        });
      },
    );

    server.registerTool(
      "get_quiz_answers",
      {
        title: "Quiz answer key — for grading attempts only",
        description:
          "The GRADING KEY for get_quiz_questions: the same quiz items including each answer. " +
          "Only call this AFTER the student has attempted the corresponding question — use it " +
          "to grade their attempt and explain the gap, never to read answers out pre-emptively.",
        inputSchema: {
          course: z.string().describe("Course id from list_courses"),
          lecture: z
            .number()
            .int()
            .min(1)
            .optional()
            .describe("Lecture number from list_lectures; omit for course-wide review"),
        },
      },
      async ({ course, lecture }) => {
        const res = await collectQuiz(course, lecture);
        if ("error" in res) return json({ error: res.error });
        return json({
          course,
          lecture: lecture ?? "all",
          total: res.items.length,
          items: res.items,
        });
      },
    );
  },
  {},
  { basePath: "/api", maxDuration: 60, verboseLogs: false },
);

// Optional token gate (enforced only when MCP_BEARER_TOKEN is set). Two ways
// to present it: the Authorization header (Claude Code / Desktop / Cursor), or
// a ?key= query parameter — for clients that can only take a URL, like the
// Claude.ai web connector. Proper per-student OAuth can replace this later.
async function guarded(req: Request): Promise<Response> {
  const token = process.env.MCP_BEARER_TOKEN;
  if (token) {
    const viaHeader = req.headers.get("authorization") === `Bearer ${token}`;
    const viaQuery = new URL(req.url).searchParams.get("key") === token;
    if (!viaHeader && !viaQuery) {
      return new Response(JSON.stringify({ error: "Unauthorized" }), {
        status: 401,
        headers: { "Content-Type": "application/json", "WWW-Authenticate": "Bearer" },
      });
    }
  }
  return handler(req);
}

export { guarded as GET, guarded as POST, guarded as DELETE };
