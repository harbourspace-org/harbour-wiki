// Lecture lifecycle + the materialized wiki store (the Obsidian+Wikipedia layer).
//
// A lecture = one row in course_session (position = lecture number) backed by
// one Knottra session. Its notes are KEPT here, in harbour_wiki.lecture_note,
// and refreshed from Knottra's delta reads (?since=cursor) while the lecture
// is live — Knottra makes the notes; the wiki keeps them.

import { q } from "./db";
import { getRecord } from "./knottra";
import type { ConceptLink, ConceptNode } from "./types";

/** Recorder restarted within this window resumes the same lecture. */
const RESUME_WINDOW_MS = 3 * 60 * 60 * 1000;
/** A live lecture's stored note older than this is re-synced on read. */
const SYNC_STALE_MS = 8_000;
/** Keep syncing this long after finalize (fusion trails the flush). */
const POST_FINAL_SYNC_MS = 15 * 60 * 1000;

export type LectureRow = {
  session_id: string;
  position: number;
  label: string | null;
  started_at: string | null;
  finalized_at: string | null;
};

export type LectureNote = {
  sessionId: string;
  courseId: string;
  cursor: number;
  concepts: ConceptNode[]; // sorted by created_at_seq (lecture order)
  links: ConceptLink[];
  narrative: string | null; // the LLM-written, timestamped story of the lecture
  narrativeCursor: number; // record cursor the narrative was written at
  narrativeAt: string | null;
};

export function sessionIdFor(courseId: string, lecture: number): string {
  return `${courseId}--l${String(lecture).padStart(2, "0")}`;
}

export async function courseLectures(courseId: string): Promise<LectureRow[]> {
  return q<LectureRow>(
    `SELECT session_id, position, label, started_at, finalized_at
     FROM harbour_wiki.course_session WHERE course_id = $1 ORDER BY position`,
    [courseId],
  );
}

export async function lectureByNumber(
  courseId: string,
  lecture: number,
): Promise<LectureRow | null> {
  const rows = await q<LectureRow>(
    `SELECT session_id, position, label, started_at, finalized_at
     FROM harbour_wiki.course_session WHERE course_id = $1 AND position = $2`,
    [courseId, lecture],
  );
  return rows[0] ?? null;
}

/**
 * "Class X is recording now" → resume the current lecture (started recently,
 * not finalized) or create the next-numbered one. The gateway decides; the
 * recorder never picks numbers or session ids.
 */
export async function startLecture(
  courseId: string,
  lectureTitle?: string,
  forceNew = false,
): Promise<{ session: string; lecture: number; resumed: boolean }> {
  const lectures = await courseLectures(courseId);
  const last = lectures[lectures.length - 1];

  const resumable =
    !forceNew &&
    last &&
    !last.finalized_at &&
    last.started_at !== null &&
    Date.now() - new Date(last.started_at).getTime() < RESUME_WINDOW_MS;

  if (resumable) {
    return { session: last.session_id, lecture: last.position, resumed: true };
  }

  const next = (last?.position ?? 0) + 1;
  const session = sessionIdFor(courseId, next);
  await q(
    `INSERT INTO harbour_wiki.course_session (course_id, session_id, position, label, started_at)
     VALUES ($1, $2, $3, $4, now())
     ON CONFLICT (course_id, session_id)
       DO UPDATE SET started_at = now(), finalized_at = NULL, label = EXCLUDED.label`,
    [courseId, session, next, lectureTitle ?? `Lecture ${next}`],
  );
  return { session, lecture: next, resumed: false };
}

export async function finalizeLecture(session: string): Promise<void> {
  await q(`UPDATE harbour_wiki.course_session SET finalized_at = now() WHERE session_id = $1`, [
    session,
  ]);
}

type NoteRow = {
  session_id: string;
  course_id: string;
  cursor: string; // bigint comes back as string
  concepts: Record<string, ConceptNode>;
  links: Record<string, ConceptLink>;
  updated_at: string;
  narrative: string | null;
  narrative_cursor: string;
  narrative_at: string | null;
};

function toNote(row: NoteRow): LectureNote {
  const concepts = Object.values(row.concepts).sort(
    (a, b) => a.created_at_seq - b.created_at_seq,
  );
  return {
    sessionId: row.session_id,
    courseId: row.course_id,
    cursor: Number(row.cursor),
    concepts,
    links: Object.values(row.links),
    narrative: row.narrative ?? null,
    narrativeCursor: Number(row.narrative_cursor ?? 0),
    narrativeAt: row.narrative_at ?? null,
  };
}

/**
 * Pull Knottra's delta past our cursor and merge it into the stored note
 * (upsert concepts/links by id — an extended concept overwrites its old copy).
 */
export async function syncLectureNote(
  courseId: string,
  session: string,
): Promise<LectureNote | null> {
  const stored = await q<NoteRow>(
    `SELECT * FROM harbour_wiki.lecture_note WHERE session_id = $1`,
    [session],
  );
  const since = stored[0] ? Number(stored[0].cursor) : 0;

  const delta = await getRecord(session, since).catch(() => null);
  if (!delta) return stored[0] ? toNote(stored[0]) : null;

  if (delta.concepts.length === 0 && delta.links.length === 0 && stored[0]) {
    return toNote(stored[0]); // nothing new fused yet
  }

  const conceptPatch = Object.fromEntries(delta.concepts.map((c) => [c.id, c]));
  const linkPatch = Object.fromEntries(delta.links.map((l) => [l.id, l]));
  const rows = await q<NoteRow>(
    `INSERT INTO harbour_wiki.lecture_note (session_id, course_id, cursor, concepts, links, updated_at)
     VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, now())
     ON CONFLICT (session_id) DO UPDATE SET
       cursor = GREATEST(harbour_wiki.lecture_note.cursor, EXCLUDED.cursor),
       concepts = harbour_wiki.lecture_note.concepts || EXCLUDED.concepts,
       links = harbour_wiki.lecture_note.links || EXCLUDED.links,
       updated_at = now()
     RETURNING *`,
    [session, courseId, delta.fused_through_seq, JSON.stringify(conceptPatch), JSON.stringify(linkPatch)],
  );
  return toNote(rows[0]);
}

/**
 * Read a lecture's notes from the wiki store — the canonical read path for
 * MCP and the web. Live (or recently finalized) lectures re-sync first when
 * the stored copy is stale, so readers always see the near-live record.
 */
export async function getLectureNote(
  courseId: string,
  session: string,
): Promise<LectureNote | null> {
  const [noteRows, lectureRows] = await Promise.all([
    q<NoteRow>(`SELECT * FROM harbour_wiki.lecture_note WHERE session_id = $1`, [session]),
    q<LectureRow>(
      `SELECT session_id, position, label, started_at, finalized_at
       FROM harbour_wiki.course_session WHERE session_id = $1`,
      [session],
    ),
  ]);
  const note = noteRows[0];
  const lecture = lectureRows[0];

  const finalizedAgo = lecture?.finalized_at
    ? Date.now() - new Date(lecture.finalized_at).getTime()
    : null;
  const stillSyncing = finalizedAgo === null || finalizedAgo < POST_FINAL_SYNC_MS;
  const stale = !note || Date.now() - new Date(note.updated_at).getTime() > SYNC_STALE_MS;

  if (stillSyncing && stale) {
    const synced = await syncLectureNote(courseId, session);
    if (synced) return synced;
  }
  return note ? toNote(note) : null;
}

/** True while the lecture is being captured (started, not finalized). */
export function isLive(l: LectureRow): boolean {
  return l.started_at !== null && l.finalized_at === null;
}

/** Regenerate the narrative at most this often for a live lecture. */
const NARRATIVE_THROTTLE_MS = 45_000;

/**
 * The whole-lecture story: LLM-rewritten, timestamped prose covering the
 * record up to its cursor. Regenerated lazily when the record has moved past
 * what the narrative covers (throttled — live polls shouldn't stampede the LLM).
 */
export async function getLectureNarrative(
  courseId: string,
  session: string,
): Promise<{ narrative: string | null; note: LectureNote } | null> {
  // Import here: narrative.ts type-imports from this module (no runtime cycle).
  const { writeNarrative } = await import("./narrative");

  const note = await getLectureNote(courseId, session);
  if (!note) return null;

  const covered = note.narrative !== null && note.narrativeCursor >= note.cursor;
  const throttled =
    note.narrativeAt !== null &&
    Date.now() - new Date(note.narrativeAt).getTime() < NARRATIVE_THROTTLE_MS;
  if (covered || (note.narrative !== null && throttled)) {
    return { narrative: note.narrative, note };
  }

  const text = await writeNarrative(note).catch(() => null);
  if (text === null) return { narrative: note.narrative, note };

  await q(
    `UPDATE harbour_wiki.lecture_note
     SET narrative = $2, narrative_cursor = $3, narrative_at = now()
     WHERE session_id = $1`,
    [session, text, note.cursor],
  );
  return { narrative: text, note };
}
