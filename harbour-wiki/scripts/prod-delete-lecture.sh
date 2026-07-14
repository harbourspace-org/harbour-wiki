#!/usr/bin/env bash
# EMERGENCY: erase a lecture COMPLETELY — wiki store row, course_session row,
# and ALL Knottra data for its session INCLUDING raw transcript events.
# For accidental recordings of private conversations: nothing survives, and
# no refold can resurrect it. Irreversible by design.
set -euo pipefail
cd "$(dirname "$0")/.."

SESSION="${1:?usage: scripts/prod-delete-lecture.sh <session-id, e.g. Linux--l05>}"

JS=$(cat <<'EOF'
const { Pool } = require("pg");
const url = process.env.APP_DATABASE_URL || process.env.DATABASE_URL;
if (!url) { console.error("no APP_DATABASE_URL/DATABASE_URL in env"); process.exit(1); }
const p = new Pool({ connectionString: url });
const SESSION = "__SESSION__";
(async () => {
  for (const [label, sql] of [
    ["wiki lecture_note", "DELETE FROM harbour_wiki.lecture_note WHERE session_id = $1"],
    ["wiki course_session", "DELETE FROM harbour_wiki.course_session WHERE session_id = $1"],
    ["knottra concepts", "DELETE FROM concepts WHERE session_id = $1"],
    ["knottra concepts_backup", "DELETE FROM concepts_backup WHERE session_id = $1"],
    ["knottra links", "DELETE FROM links WHERE session_id = $1"],
    ["knottra window_fusions", "DELETE FROM window_fusions WHERE session_id = $1"],
    ["knottra events (raw transcript)", "DELETE FROM events WHERE session_id = $1"],
    ["knottra sessions", "DELETE FROM sessions WHERE session_id = $1"],
  ]) {
    const r = await p.query(sql, [SESSION]);
    console.log(`${label}: ${r.rowCount} rows deleted`);
  }
  await p.end();
})().catch((e) => { console.error(e); process.exit(1); });
EOF
)
JS="${JS//__SESSION__/$SESSION}"
B64=$(printf '%s' "$JS" | base64 | tr -d '\n')

railway ssh --service harbour-wiki -- "echo $B64 | base64 -d | node"
