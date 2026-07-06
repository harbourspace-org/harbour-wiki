import { randomUUID } from "node:crypto";

import { q } from "./db";

export type Annotation = {
  id: string;
  concept_id: string;
  body: string;
  author: string | null;
  created_at: string;
};
export type UserLink = {
  id: string;
  from_concept: string;
  to_concept: string;
  kind: string;
};

export async function listAnnotations(courseId: string, conceptId: string): Promise<Annotation[]> {
  return q<Annotation>(
    `SELECT id, concept_id, body, author, created_at FROM harbour_wiki.annotation
     WHERE course_id = $1 AND concept_id = $2 ORDER BY created_at`,
    [courseId, conceptId],
  );
}

export async function createAnnotation(
  courseId: string,
  conceptId: string,
  body: string,
  author?: string,
): Promise<Annotation> {
  const id = randomUUID();
  const rows = await q<Annotation>(
    `INSERT INTO harbour_wiki.annotation (id, course_id, concept_id, body, author)
     VALUES ($1, $2, $3, $4, $5)
     RETURNING id, concept_id, body, author, created_at`,
    [id, courseId, conceptId, body, author ?? null],
  );
  return rows[0];
}

export async function listUserLinks(courseId: string): Promise<UserLink[]> {
  return q<UserLink>(
    "SELECT id, from_concept, to_concept, kind FROM harbour_wiki.user_link WHERE course_id = $1",
    [courseId],
  );
}

export async function createUserLink(
  courseId: string,
  from: string,
  to: string,
  kind: string,
): Promise<void> {
  await q(
    `INSERT INTO harbour_wiki.user_link (id, course_id, from_concept, to_concept, kind)
     VALUES ($1, $2, $3, $4, $5)`,
    [randomUUID(), courseId, from, to, kind || "related"],
  );
}
