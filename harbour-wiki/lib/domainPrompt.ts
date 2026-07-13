// The fusion domain prompt — how "this is a lecture" enters the (domain-blind)
// Knottra engine. Shared by lecture start (/api/ingest) and admin refold, so
// re-fused lectures always get the CURRENT prompt, not the one stored when
// they were first recorded.

export const DEFAULT_DOMAIN_PROMPT = [
  "This is a university lecture. You are writing a permanent study wiki, not",
  "meeting minutes: each concept is an encyclopedia entry a student will",
  "revise from later, long after the class is forgotten.",
  "Titles must be noun phrases naming the concept itself (e.g.",
  "'Breadth-First Search'), never the classroom moment — no 'Introduction to",
  "the lecture', no titles containing 'lecture' or 'lecturer'.",
  "Details and sub-points must state definitions, properties, complexity,",
  "formulas, and worked examples directly as facts. Never narrate the",
  "classroom: no 'the lecturer/professor/instructor explains', 'is",
  "introduced', or 'we now move on' — convert transition remarks into the",
  "actual content they carry, or omit them. Prefer extending an existing",
  "open concept over opening a near-duplicate, and do not open concepts for",
  "administrative chatter or jokes.",
  "OFF-TOPIC GUARD: the microphone runs continuously, so windows may contain",
  "material that is not course content at all — scheduling and administrative",
  "talk, small talk before/after class, weather, personal conversations,",
  "questions about deadlines or attendance. Emit NO concepts for such",
  "material: if a window holds only off-topic speech, emit an empty concept",
  "list rather than structuring it. Never include personal or private details",
  "about identifiable people (names tied to grades, health, opinions) in any",
  "concept.",
].join(" ");
