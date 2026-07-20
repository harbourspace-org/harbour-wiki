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
ALTER TABLE harbour_wiki.course_session ADD COLUMN IF NOT EXISTS started_at timestamptz;
ALTER TABLE harbour_wiki.course_session ADD COLUMN IF NOT EXISTS finalized_at timestamptz;
-- Last ingest activity; the resume window slides on this, not on started_at,
-- so lectures longer than the window don't spawn phantom successors.
ALTER TABLE harbour_wiki.course_session ADD COLUMN IF NOT EXISTS last_seen_at timestamptz;
-- The materialized wiki store: the lecture's notes, KEPT here permanently
-- (the Obsidian+Wikipedia layer). Synced from Knottra deltas while LIVE.
CREATE TABLE IF NOT EXISTS harbour_wiki.lecture_note (
  session_id text PRIMARY KEY,
  course_id text NOT NULL,
  cursor bigint NOT NULL DEFAULT 0,
  concepts jsonb NOT NULL DEFAULT '{}'::jsonb,
  links jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now()
);
-- The LLM-rewritten whole-lecture story (timestamped prose conspect).
ALTER TABLE harbour_wiki.lecture_note ADD COLUMN IF NOT EXISTS narrative text;
ALTER TABLE harbour_wiki.lecture_note ADD COLUMN IF NOT EXISTS narrative_cursor bigint NOT NULL DEFAULT 0;
ALTER TABLE harbour_wiki.lecture_note ADD COLUMN IF NOT EXISTS narrative_at timestamptz;
CREATE INDEX IF NOT EXISTS ix_lecture_note_course ON harbour_wiki.lecture_note (course_id);
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
-- Usage/feedback log: which surfaces and tools students actually use, plus
-- their votes — the data the feedback experiment is judged on.
CREATE TABLE IF NOT EXISTS harbour_wiki.usage_event (
  id bigserial PRIMARY KEY,
  at timestamptz NOT NULL DEFAULT now(),
  surface text NOT NULL,        -- mcp | web | ask | feedback
  name text NOT NULL,           -- tool/action name (get_lecture, course_view, vote…)
  course text,
  meta jsonb
);
CREATE INDEX IF NOT EXISTS ix_usage_event_at ON harbour_wiki.usage_event (at);
-- Classroom capture agents report their health here. This table deliberately
-- stores the latest snapshot only; lecture events remain in course_session.
CREATE TABLE IF NOT EXISTS harbour_wiki.capture_agent (
  agent_id text PRIMARY KEY,
  hostname text NOT NULL,
  scheduler_status text NOT NULL,
  session_id text,
  current_course_id text,
  current_course_name text,
  current_lecture int,
  current_slot int,
  current_started_at timestamptz,
  current_ends_at timestamptz,
  next_course_id text,
  next_course_name text,
  next_lecture int,
  next_slot int,
  next_starts_at timestamptz,
  next_ends_at timestamptz,
  audio_status text NOT NULL,
  camera_status text NOT NULL,
  zoom_status text NOT NULL,
  outbox_pending int NOT NULL DEFAULT 0,
  errors jsonb NOT NULL DEFAULT '[]'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS harbour_wiki.capture_command (
  id bigserial PRIMARY KEY,
  agent_id text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('stop', 'extend', 'skip')),
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'acknowledged', 'failed')),
  created_at timestamptz NOT NULL DEFAULT now(),
  delivered_at timestamptz,
  completed_at timestamptz,
  result text,
  error text
);
CREATE INDEX IF NOT EXISTS ix_capture_command_pending
  ON harbour_wiki.capture_command (agent_id, status, created_at);
-- Per-agent timetable, uploaded from an operator's laptop and pulled by the
-- lecture PC so recordings start on schedule without touching the machine.
-- The version is opaque and server-owned — the agent echoes it back to detect
-- changes. body is the raw schedule JSON the capture side validates.
CREATE TABLE IF NOT EXISTS harbour_wiki.capture_schedule (
  agent_id text PRIMARY KEY,
  body jsonb NOT NULL,
  version text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);
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
