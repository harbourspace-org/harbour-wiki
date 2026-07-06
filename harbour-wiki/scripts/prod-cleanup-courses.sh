#!/usr/bin/env bash
# One-off: delete all courses/lectures from the production wiki DB except KEEP.
# Runs node+pg inside the harbour-wiki Railway container (no creds leave prod).
# The JS is base64-encoded in transit because `railway ssh` flattens argument
# quoting; the cleartext script is right here below.
set -euo pipefail
cd "$(dirname "$0")/.."

KEEP="${1:-Linux}"

JS=$(cat <<'EOF'
const { Pool } = require("pg");
const url = process.env.APP_DATABASE_URL || process.env.DATABASE_URL;
if (!url) { console.error("no APP_DATABASE_URL/DATABASE_URL in env"); process.exit(1); }
const p = new Pool({ connectionString: url });
const KEEP = "__KEEP__";
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
EOF
)
JS="${JS//__KEEP__/$KEEP}"
B64=$(printf '%s' "$JS" | base64 | tr -d '\n')

railway ssh --service harbour-wiki -- "echo $B64 | base64 -d | node"
