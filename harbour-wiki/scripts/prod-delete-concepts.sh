#!/usr/bin/env bash
# One-off: scrub specific concepts from a lecture, in both stores —
# harbour_wiki.lecture_note (JSONB) and Knottra's concepts/links tables.
# Matched by title prefix. Also nulls the narrative so it regenerates clean.
set -euo pipefail
cd "$(dirname "$0")/.."

SESSION="${1:-Linux--l02}"

JS=$(cat <<'EOF'
const { Pool } = require("pg");
const url = process.env.APP_DATABASE_URL || process.env.DATABASE_URL;
if (!url) { console.error("no APP_DATABASE_URL/DATABASE_URL in env"); process.exit(1); }
const p = new Pool({ connectionString: url });
const SESSION = "__SESSION__";
const PREFIXES = [
  "Administrative Preference Check",
  "Temperature Distribution in France and Spain",
  "Web Content Instability",
];
const matches = (t) => PREFIXES.some((pre) => (t || "").startsWith(pre));
(async () => {
  const { rows } = await p.query(
    "SELECT concepts, links FROM harbour_wiki.lecture_note WHERE session_id = $1", [SESSION]);
  if (!rows[0]) { console.error("no lecture_note for " + SESSION); process.exit(1); }
  // concepts/links are JSONB objects keyed by id
  const concepts = rows[0].concepts || {};
  const links = rows[0].links || {};
  const doomed = Object.values(concepts).filter((c) => matches(c.title));
  console.log("wiki store matches:", doomed.map((c) => `${c.id} ${c.title}`));
  const ids = new Set(doomed.map((c) => c.id));
  const keptConcepts = Object.fromEntries(
    Object.entries(concepts).filter(([id]) => !ids.has(id)));
  const keptLinks = Object.fromEntries(
    Object.entries(links).filter(([, l]) => !ids.has(l.from) && !ids.has(l.to)));
  await p.query(
    `UPDATE harbour_wiki.lecture_note
     SET concepts = $2, links = $3, narrative = NULL, narrative_cursor = 0
     WHERE session_id = $1`,
    [SESSION, JSON.stringify(keptConcepts), JSON.stringify(keptLinks)]);
  console.log(`wiki store: ${doomed.length} concepts removed, ${Object.keys(keptConcepts).length} kept`);

  const like = PREFIXES.map((_, i) => `title LIKE $${i + 2} || '%'`).join(" OR ");
  const kc = await p.query(
    `SELECT id, title FROM concepts WHERE session_id = $1 AND (${like})`,
    [SESSION, ...PREFIXES]);
  console.log("knottra matches:", kc.rows.map((r) => `${r.id} ${r.title}`));
  const kids = kc.rows.map((r) => r.id);
  if (kids.length) {
    const del1 = await p.query("DELETE FROM concepts WHERE id = ANY($1) AND session_id = $2", [kids, SESSION]);
    const del2 = await p.query(
      "DELETE FROM links WHERE session_id = $1 AND (from_concept = ANY($2) OR to_concept = ANY($2))",
      [SESSION, kids]);
    const del3 = await p.query(
      `DELETE FROM concepts_backup WHERE session_id = $1 AND (${like})`, [SESSION, ...PREFIXES]);
    console.log(`knottra: ${del1.rowCount} concepts, ${del2.rowCount} links, ${del3.rowCount} backups deleted`);
  }
  await p.end();
})().catch((e) => { console.error(e); process.exit(1); });
EOF
)
JS="${JS//__SESSION__/$SESSION}"
B64=$(printf '%s' "$JS" | base64 | tr -d '\n')

railway ssh --service harbour-wiki -- "echo $B64 | base64 -d | node"
