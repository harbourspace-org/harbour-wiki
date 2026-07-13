// Weave a whole course's lectures into one linked graph — read from the WIKI
// STORE (harbour_wiki.lecture_note), the permanent Obsidian+Wikipedia layer.
// Live lectures re-sync from Knottra inside getLectureNote; finalized ones are
// served straight from the store. Student-authored cross-lecture links are
// merged in, with an outgoing/backlink index.

import { listUserLinks } from "./annotations";
import { getCourse, type Course } from "./courses";
import {
  courseLectures,
  getLectureNarrative,
  getLectureNote,
  isLive,
  isReceiving,
  silentForSeconds,
} from "./lectures";
import { isLegacyConspect } from "./narrative";
import type { ConceptNode } from "./types";

export type AggConcept = ConceptNode & { sessionId: string; lecture: string };
export type AggLink = {
  from: string;
  to: string;
  kind: string;
  source: "knottra" | "student";
};
export type Lecture = {
  sessionId: string;
  number: number;
  label: string;
  live: boolean;
  /** LIVE and events arrived within the last minute — the recorder is alive. */
  receiving: boolean;
  /** Seconds since the last ingested event (for the stale-LIVE warning). */
  silentFor: number | null;
  narrative: string | null;
  concepts: AggConcept[];
};

export type CourseGraph = {
  course: Course;
  lectures: Lecture[];
  conceptsById: Map<string, AggConcept>;
  outgoing: Map<string, AggLink[]>;
  backlinks: Map<string, AggLink[]>;
};

/** Self-heal at most this many missing/stale conspects per page build. */
const NARRATIVE_HEALS_PER_BUILD = 2;

export async function buildCourseGraph(courseId: string): Promise<CourseGraph | null> {
  const course = await getCourse(courseId);
  if (!course) return null;

  const rows = await courseLectures(courseId);
  const notes = await Promise.all(
    rows.map((l) => getLectureNote(courseId, l.session_id).catch(() => null)),
  );

  // Self-heal: finalized lectures with concepts but a missing, stale, or
  // format-stale (pre-quiz "legacy") narrative regenerate it here, so
  // conspects appear on the web without an MCP get_lecture call. Bounded per
  // build, and getLectureNarrative's own 45s throttle keeps page views from
  // stampeding the LLM.
  const healable = rows
    .map((row, i) => ({ row, i, note: notes[i] }))
    .filter(
      ({ row, note }) =>
        note !== null &&
        !isLive(row) &&
        note.concepts.length > 0 &&
        (note.narrative === null ||
          note.narrativeCursor < note.cursor ||
          isLegacyConspect(note.narrative)),
    )
    .slice(0, NARRATIVE_HEALS_PER_BUILD);
  const healed = await Promise.all(
    healable.map(({ row }) => getLectureNarrative(courseId, row.session_id).catch(() => null)),
  );
  healed.forEach((h, j) => {
    if (h) notes[healable[j].i] = { ...h.note, narrative: h.narrative };
  });

  const lectures: Lecture[] = [];
  const conceptsById = new Map<string, AggConcept>();
  const outgoing = new Map<string, AggLink[]>();
  const backlinks = new Map<string, AggLink[]>();

  const addLink = (l: AggLink) => {
    (outgoing.get(l.from) ?? outgoing.set(l.from, []).get(l.from)!).push(l);
    (backlinks.get(l.to) ?? backlinks.set(l.to, []).get(l.to)!).push(l);
  };

  rows.forEach((row, i) => {
    const note = notes[i];
    const label = row.label || row.session_id;
    const concepts: AggConcept[] = (note?.concepts ?? []).map((c) => ({
      ...c,
      sessionId: row.session_id,
      lecture: label,
    }));
    concepts.forEach((c) => conceptsById.set(c.id, c));
    lectures.push({
      sessionId: row.session_id,
      number: row.position,
      label,
      live: isLive(row),
      receiving: isReceiving(row),
      silentFor: silentForSeconds(row),
      narrative: note?.narrative ?? null,
      concepts,
    });
    for (const link of note?.links ?? []) {
      addLink({ from: link.from_concept, to: link.to_concept, kind: link.kind, source: "knottra" });
    }
  });

  // Student-authored cross-lecture links.
  for (const ul of await listUserLinks(courseId)) {
    addLink({ from: ul.from_concept, to: ul.to_concept, kind: ul.kind, source: "student" });
  }

  return { course, lectures, conceptsById, outgoing, backlinks };
}
