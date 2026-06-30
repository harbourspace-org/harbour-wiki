// Weave a whole course's lectures into one linked graph: union of each
// session's Knottra record (intra-lecture links) + student-authored cross-lecture
// links, with an outgoing/backlink index.

import { listUserLinks } from "./annotations";
import { courseSessions, getCourse, type Course } from "./courses";
import { getRecord } from "./knottra";
import type { ConceptNode } from "./types";

export type AggConcept = ConceptNode & { sessionId: string; lecture: string };
export type AggLink = {
  from: string;
  to: string;
  kind: string;
  source: "knottra" | "student";
};
export type Lecture = { sessionId: string; label: string; concepts: AggConcept[] };

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

  const sessions = await courseSessions(courseId);
  const records = await Promise.all(
    sessions.map((s) => getRecord(s.session_id).catch(() => null)),
  );

  const lectures: Lecture[] = [];
  const conceptsById = new Map<string, AggConcept>();
  const outgoing = new Map<string, AggLink[]>();
  const backlinks = new Map<string, AggLink[]>();

  const addLink = (l: AggLink) => {
    (outgoing.get(l.from) ?? outgoing.set(l.from, []).get(l.from)!).push(l);
    (backlinks.get(l.to) ?? backlinks.set(l.to, []).get(l.to)!).push(l);
  };

  sessions.forEach((s, i) => {
    const rec = records[i];
    const label = s.label || s.session_id;
    if (!rec) {
      lectures.push({ sessionId: s.session_id, label, concepts: [] });
      return;
    }
    const concepts: AggConcept[] = rec.concepts.map((c) => ({
      ...c,
      sessionId: s.session_id,
      lecture: label,
    }));
    concepts.forEach((c) => conceptsById.set(c.id, c));
    lectures.push({ sessionId: s.session_id, label, concepts });
    for (const link of rec.links) {
      addLink({ from: link.from_concept, to: link.to_concept, kind: link.kind, source: "knottra" });
    }
  });

  // Student-authored cross-lecture links.
  for (const ul of await listUserLinks(courseId)) {
    addLink({ from: ul.from_concept, to: ul.to_concept, kind: ul.kind, source: "student" });
  }

  return { course, lectures, conceptsById, outgoing, backlinks };
}
