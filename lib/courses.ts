import { q } from "./db";

export type Course = { id: string; title: string; domain_prompt: string | null };
export type CourseSession = { session_id: string; position: number; label: string | null };

export async function listCourses(): Promise<Course[]> {
  return q<Course>("SELECT id, title, domain_prompt FROM harbour_wiki.course ORDER BY created_at");
}

export async function getCourse(id: string): Promise<Course | null> {
  const rows = await q<Course>(
    "SELECT id, title, domain_prompt FROM harbour_wiki.course WHERE id = $1",
    [id],
  );
  return rows[0] ?? null;
}

export async function courseSessions(courseId: string): Promise<CourseSession[]> {
  return q<CourseSession>(
    "SELECT session_id, position, label FROM harbour_wiki.course_session WHERE course_id = $1 ORDER BY position",
    [courseId],
  );
}

export async function upsertCourse(id: string, title: string, domainPrompt?: string): Promise<void> {
  await q(
    `INSERT INTO harbour_wiki.course (id, title, domain_prompt) VALUES ($1, $2, $3)
     ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title, domain_prompt = EXCLUDED.domain_prompt`,
    [id, title, domainPrompt ?? null],
  );
}

export async function addCourseSession(
  courseId: string,
  sessionId: string,
  position: number,
  label: string,
): Promise<void> {
  await q(
    `INSERT INTO harbour_wiki.course_session (course_id, session_id, position, label)
     VALUES ($1, $2, $3, $4)
     ON CONFLICT (course_id, session_id) DO UPDATE SET position = EXCLUDED.position, label = EXCLUDED.label`,
    [courseId, sessionId, position, label],
  );
}
