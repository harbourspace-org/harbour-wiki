// Weave a whole course's lectures into one linked graph — read from the WIKI
// STORE (harbour_wiki.lecture_note), the permanent Obsidian+Wikipedia layer.
// Live lectures re-sync from Knottra inside getLectureNote; finalized ones are
// served straight from the store. Student-authored cross-lecture links are
// merged in, with an outgoing/backlink index.

import { listUserLinks } from "./annotations";
import { getCourse, type Course } from "./courses";
import { courseLectures, getLectureNote, isLive } from "./lectures";
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
  concepts: AggConcept[];
};

export type CourseGraph = {
  course: Course;
  lectures: Lecture[];
  conceptsById: Map<string, AggConcept>;
  outgoing: Map<string, AggLink[]>;
  backlinks: Map<string, AggLink[]>;
};

export async function buildCourseGraph(courseId: string): Promise<CourseGraph | null> {
  const course = await getCourse(courseId);
  if (!course) return null;

  const rows = await courseLectures(courseId);
  const notes = await Promise.all(
    rows.map((l) => getLectureNote(courseId, l.session_id).catch(() => null)),
  );

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
