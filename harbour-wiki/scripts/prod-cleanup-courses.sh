#!/usr/bin/env bash
# One-off: delete all courses/lectures from the production wiki DB except KEEP.
# Runs node+pg inside the harbour-wiki Railway container (no creds leave prod).
set -euo pipefail
cd "$(dirname "$0")/.."

KEEP="${1:-Linux}"

railway ssh --service harbour-wiki -- node -e '
const { Pool } = require("pg");
const p = new Pool({ connectionString: process.env.DATABASE_URL });
const KEEP = "'"$KEEP"'";
(async () => {
  for (const t of ["annotation", "user_link", "lecture_note", "course_session"]) {
    const r = await p.query(
      `DELETE FROM harbour_wiki.${t} WHERE course_id IS DISTINCT FROM $1`, [KEEP]);
    console.log(`${t}: ${r.rowCount} rows deleted`);
  }
  const c = await p.query("DELETE FROM harbour_wiki.course WHERE id <> $1", [KEEP]);
  console.log(`course: ${c.rowCount} rows deleted`);
  const left = await p.query("SELECT id, title FROM harbour_wiki.course");
  console.log("remaining courses:", JSON.stringify(left.rows));
  await p.end();
})().catch((e) => { console.error(e); process.exit(1); });
'
