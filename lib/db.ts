// App-side Postgres (the human layer: courses, annotations, student links).
// Lives in its own `harbour_wiki` schema, separate from the Knottra engine's
// tables — swap APP_DATABASE_URL for a dedicated DB in production.

import { Pool } from "pg";

const APP_DB =
  process.env.APP_DATABASE_URL ?? "postgresql://knottra:knottra@localhost:5432/knottra";

declare global {
  // eslint-disable-next-line no-var
  var _hwPool: Pool | undefined;
  // eslint-disable-next-line no-var
  var _hwReady: Promise<void> | undefined;
}

export const pool = global._hwPool ?? new Pool({ connectionString: APP_DB });
if (!global._hwPool) global._hwPool = pool;

const SCHEMA = `
CREATE SCHEMA IF NOT EXISTS harbour_wiki;
CREATE TABLE IF NOT EXISTS harbour_wiki.course (
  id text PRIMARY KEY,
  title text NOT NULL,
  domain_prompt text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS harbour_wiki.course_session (
  course_id text NOT NULL REFERENCES harbour_wiki.course(id) ON DELETE CASCADE,
  session_id text NOT NULL,
  position int NOT NULL DEFAULT 0,
  label text,
  PRIMARY KEY (course_id, session_id)
);
CREATE TABLE IF NOT EXISTS harbour_wiki.annotation (
  id text PRIMARY KEY,
  course_id text NOT NULL,
  concept_id text NOT NULL,
  body text NOT NULL,
  author text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_annotation_concept ON harbour_wiki.annotation (course_id, concept_id);
CREATE TABLE IF NOT EXISTS harbour_wiki.user_link (
  id text PRIMARY KEY,
  course_id text NOT NULL,
  from_concept text NOT NULL,
  to_concept text NOT NULL,
  kind text NOT NULL DEFAULT 'related',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_user_link_course ON harbour_wiki.user_link (course_id);
`;

export function ready(): Promise<void> {
  if (!global._hwReady) {
    global._hwReady = pool.query(SCHEMA).then(() => undefined);
  }
  return global._hwReady;
}

export async function q<T = unknown>(text: string, params: unknown[] = []): Promise<T[]> {
  await ready();
  const r = await pool.query(text, params);
  return r.rows as T[];
}
