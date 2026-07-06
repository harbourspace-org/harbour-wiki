# Harbour.Wiki — Pipeline Design (course → lecture hierarchy)

> Status: PROPOSED — awaiting Ivan's confirmation before implementation.
> This redesign makes the **class/course → lecture** hierarchy the organizing
> principle of the whole system, and makes **real-time MCP access to a concrete
> lecture** the primary product surface (web rendering is secondary).

---

## 0. Division of labour — the point everyone must understand

**KNOTTRA — the real-time note-maker (the brain).**
During a lecture, in real time, it:
1. builds everything needed to answer questions — concepts, sub-points,
   logical links, embeddings ("the database");
2. makes the **notes of the current lecture** and keeps refreshing them,
   window by window, as the lecturer speaks (extend concept / open concept).
It answers *data* queries only (record, deltas via `?since=`, semantic
search) and knows nothing about courses, lectures, or students.

**HARBOUR.WIKI — the keeper of the lectures (Obsidian + Wikipedia).**
It **KEEPS** every lecture permanently as wiki material:
- a **note page per lecture** (the conspect) — refreshed live while the
  lecture is being taught;
- a **page per concept** with links and **backlinks** (Obsidian-style),
  together forming a browsable encyclopedia of everything taught
  (Wikipedia-style);
- the **course → lecture tree** (titles, numbering, LIVE status);
- the access doors: **MCP** (primary — students ask questions) and the web
  wiki (secondary — browsing), plus the single capture gateway.

**The live-sync rule that ties them:** while a lecture is LIVE, Harbour.Wiki
pulls Knottra's record delta (`GET /record?since=<cursor>`, ~every 10s) and
upserts its own stored pages — so the current lecture's notes refresh in
real time *inside the wiki*, and remain there forever after the lecture ends
(one final sync at flush). Knottra produces the notes; Harbour.Wiki keeps them.

---

## 1. The domain model

```
CLASS (course)                e.g. "algorithms-2026" — Algorithms & Data Structures
 ├── Lecture 1                one physical lecture = one Knottra session
 ├── Lecture 2                    session_id = "algorithms-2026--l02"
 ├── …
 └── Lecture N  ◀── LIVE      the lecture being captured right now
```

- **Class (course):** stable id + title + domain prompt. Created once, reused
  every lecture. Lives in Harbour.Wiki's own DB (`harbour_wiki.course`).
- **Lecture:** one recording session. Auto-numbered within its course
  (position 1, 2, 3…), has a title/label and a date. Maps 1:1 to a Knottra
  session. Lives in `harbour_wiki.course_session` (course_id, session_id,
  position, label).
- **Knottra stays hierarchy-blind** (its hard rule: no domain knowledge).
  The course→lecture structure lives entirely in Harbour.Wiki; Knottra only
  ever sees opaque session ids.

**Session id convention:** `{course_id}--l{NN}` (e.g. `algorithms-2026--l05`).
Deterministic, readable, collision-free — and derivable in both directions.

---

## 2. Capture: "class X is recording now"

The operator on the lecture PC specifies **only the class**. The system
figures out the lecture.

```
lecture-capture --class algorithms-2026 [--lecture-title "Hashing"]
```

Startup handshake (new):

```
recorder ──▶ POST /api/ingest {action:"start", course:{id,title?}, lectureTitle?}
         ◀── {session:"algorithms-2026--l05", lecture:5, resumed:false}
```

- The **gateway decides the lecture number**: it looks at the course's
  existing lectures and creates the next one (position = max+1). The recorder
  never guesses.
- **Resume rule:** if the newest lecture of that course was started < N hours
  ago (default 3h) and is not finalized, `start` returns *the same* session —
  so a recorder crash/restart mid-lecture appends to the correct lecture
  instead of opening a phantom new one. `--new-lecture` forces a new one.
- Then the recorder streams as today: chunks → `{session, events:[…]}`,
  Ctrl+C → `{session, flush:true}` which also marks the lecture finalized.

The recorder still holds only `CAPTURE_TOKEN` — never the Knottra key.

---

## 3. Ingest gateway (Harbour.Wiki, the single door to Knottra)

`POST /api/ingest` becomes action-shaped:

| Action | Body | Effect |
|---|---|---|
| `start` | `{action:"start", course:{id,title?}, lectureTitle?, forceNew?}` | Upsert course; create-or-resume the current lecture; PUT Knottra session config (course domain prompt); return `{session, lecture}` |
| `events` | `{session, events:[…]}` | Validate → forward to Knottra `POST /events` |
| `flush` | `{session, flush:true}` | Forward flush; mark lecture `finalized_at` |

DB change: `course_session` gains `started_at` and `finalized_at`
(for the resume rule and for "which lecture is LIVE").

Everything Knottra-facing keeps using the app's single `KNOTTRA_API_KEY`
(single-tenant-key model → the app can always read every lecture).

---

## 4. MCP: the primary student surface

A student connects Claude (web/desktop) to `/api/mcp` and works with the
course→lecture tree. Tool set redesigned around the hierarchy:

| Tool | Args | Returns |
|---|---|---|
| `list_courses` | — | courses (id, title, lectures count, which lecture is LIVE now) |
| `list_lectures` | `course` | lectures with number, title, date, concept count, `live: true/false` |
| `get_lecture` | `course, lecture` (number) | the lecture's full fused record (concepts, sub-points, links) |
| `get_lecture_updates` | `course, lecture, since` | **real-time delta**: only concepts/links fused after cursor `since` (maps to Knottra `?since=`), plus the new cursor. Claude polls this during a live lecture. |
| `search_lecture` | `course, lecture, query` | semantic search **inside one lecture** |
| `search_course` | `course, query` | semantic search **across all lectures** of the course (today's `search_lectures`) |
| `get_concept` | `course, concept_id` | one concept + links/backlinks (unchanged) |

**The two study flows this enables:**

1. **Live lecture:** student sits in (or missed the start of) Lecture 5.
   Claude: `list_courses` → sees `algorithms-2026` has Lecture 5 LIVE →
   `get_lecture(…, 5)` for everything so far → then `get_lecture_updates`
   with the returned cursor to pull only what's new → answers questions
   grounded in the growing record. Fusion lag ≈ chunk (6s) + window (10s) +
   LLM fold — the record trails the lecturer by well under a minute.
2. **Course-wide question:** "how does today's hashing relate to lecture 2's
   arrays?" → `search_course` grounds the answer across all structured
   lectures of the class.

Addressing is always **(course, lecture number)** — students never see raw
session ids.

---

## 5. End-to-end flow (one lecture day)

```
[lecture PC, Windows]                     [Railway]
─────────────────────                     ──────────────────────────────────────
lecture-capture --class algorithms-2026
  │ start ─────────────────────────────▶ Harbour.Wiki /api/ingest
  │                                        ├─ upsert course "algorithms-2026"
  │                                        ├─ next lecture → #5, session
  │                                        │    "algorithms-2026--l05"
  │ ◀─ {session, lecture:5} ───────────────┴─ PUT Knottra /config (domain prompt)
  │
  │ 🎤 → whisper → text chunk (6s)
  │ events ────────────────────────────▶ /api/ingest → Knottra /events
  │        …repeat all lecture…              └─ worker fuses → concepts grow
  │
  │            (meanwhile) student in Claude: get_lecture(algorithms-2026, 5)
  │                        → get_lecture_updates(…, since) → live Q&A
  │
  │ Ctrl+C
  │ flush ─────────────────────────────▶ /api/ingest → Knottra /flush
                                           └─ lecture 5 marked finalized
Next week: same command, same class → lecture #6 automatically.
```

---

## 6. What changes vs. today's code

| Component | Change |
|---|---|
| **Wiki store (new)** | `harbour_wiki.lecture_note` (session_id, cursor, concepts/links JSONB, updated_at): the materialized, permanently-kept notes. Concept pages + backlinks derived from it. |
| **Live sync (new)** | while a lecture is LIVE: pull Knottra `?since=cursor` ~every 10s and upsert the stored page; final sync at flush. MCP/web read the wiki store (fall back to Knottra only if a page is missing). |
| `harbour_wiki.course_session` | + `started_at`, `finalized_at` columns; positions become real (1..N, auto-next) |
| `/api/ingest` | + `start` action (create-or-resume lecture, auto-number); `flush` also finalizes |
| `/api/mcp` | retool around (course, lecture): + `get_lecture`, `get_lecture_updates` (real-time delta), `search_lecture`; rename `search_lectures`→`search_course`; enrich `list_*` with live/date info |
| `lecture-capture` CLI | `--class` (required) + `--lecture-title` + `--new-lecture` replace `--session/--course/--label`; startup handshake gets the session from the gateway |
| `lib/knottra.ts` | expose `since` on `getRecord` (Knottra already supports `?since=` — unused so far) |
| Web UI | already course→lecture shaped (`/course/[id]`, `/wiki/[session]`); minor: show LIVE badge + lecture numbers |
| Knottra engine | **no changes** — hierarchy stays out of the engine by design |

Out of scope for this iteration (explicitly): student auth on MCP (OAuth),
board/slide modalities, offline record-and-sync, Windows system-audio loopback.
Each slots in cleanly later without changing this design.

---

## 7. Open questions for Ivan

1. **Resume window** — 3h OK? (recorder restarted within 3h of start continues
   the same lecture unless `--new-lecture`.)
2. **Lecture titles** — optional `--lecture-title` at start, or set/rename later
   in the wiki? (Design allows both.)
3. **MCP auth** — endpoint currently token-gated (Claude-web unfriendly). For
   the student flow: keep bearer (Desktop/Cursor only), or move to OAuth later?
