// ASR post-correction: a small, fast model fixes what Whisper misheard
// ("causing this book" → "causing this bug") BEFORE fusion, using the
// course's own terminology as context. Transcript quality is the ceiling of
// everything downstream, and a cheap contextual pass beats a bigger local
// STT model (benchmarked: large models can't keep up with live speech).

import { courseVocabulary } from "./lectures";

const LLM_BASE = process.env.LLM_BASE_URL ?? "https://opencode.ai/zen/v1";
const LLM_KEY = process.env.LLM_API_KEY ?? "";
// Deliberately a small/fast model — this runs on every utterance.
const FIX_MODEL = process.env.ASR_FIX_MODEL ?? "claude-haiku-4-5";

const TIMEOUT_MS = 6_000; // never make the recorder wait long for a nicety
const MAX_UTTERANCE_CHARS = 1_500;

// The course vocabulary barely changes within a lecture — cache it.
const vocabCache = new Map<string, { terms: string[]; at: number }>();
const VOCAB_TTL_MS = 5 * 60_000;

async function vocabulary(courseId: string): Promise<string[]> {
  const hit = vocabCache.get(courseId);
  if (hit && Date.now() - hit.at < VOCAB_TTL_MS) return hit.terms;
  const terms = await courseVocabulary(courseId).catch(() => []);
  vocabCache.set(courseId, { terms, at: Date.now() });
  return terms;
}

/**
 * Return the corrected utterance, or the original on any failure/timeout —
 * correction is best-effort and must never block or break ingest.
 */
export async function correctTranscript(text: string, courseId: string): Promise<string> {
  if (!LLM_KEY || text.length > MAX_UTTERANCE_CHARS) return text;
  const terms = await vocabulary(courseId);

  try {
    const resp = await fetch(`${LLM_BASE}/chat/completions`, {
      method: "POST",
      headers: { Authorization: `Bearer ${LLM_KEY}`, "Content-Type": "application/json" },
      signal: AbortSignal.timeout(TIMEOUT_MS),
      body: JSON.stringify({
        model: FIX_MODEL,
        max_tokens: 400,
        messages: [
          {
            role: "system",
            content:
              "You fix speech-recognition errors in single utterances from a " +
              `university lecture (course: ${courseId}). ` +
              (terms.length ? `Known course terms: ${terms.slice(0, 30).join("; ")}. ` : "") +
              "Correct ONLY clear mishearings — homophones, garbled technical " +
              "terms, broken words ('this book' → 'this bug' when the course " +
              "context makes it obvious). Never add, remove, summarize, or " +
              "rephrase content; keep filler words and sentence structure. If " +
              "the utterance is fine or you are unsure, return it unchanged. " +
              "Reply with the utterance text only — no quotes, no commentary.",
          },
          { role: "user", content: text },
        ],
      }),
    });
    if (!resp.ok) return text;
    const data = await resp.json();
    const fixed: string = data?.choices?.[0]?.message?.content?.trim() ?? "";
    // Guard against model misbehavior: a correction should look like the
    // original (similar length), not an answer or a summary.
    if (!fixed || fixed.length < text.length * 0.5 || fixed.length > text.length * 1.6) {
      return text;
    }
    return fixed;
  } catch {
    return text;
  }
}
