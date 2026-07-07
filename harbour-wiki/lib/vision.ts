// Vision extraction for the camera agent: a lecture frame (whiteboard / slide /
// desk) goes in, already-extracted TEXT comes out — which is all Knottra ever
// ingests. Runs server-side so lecture PCs never hold the LLM key.

const LLM_BASE = process.env.LLM_BASE_URL ?? "https://opencode.ai/zen/v1";
const LLM_KEY = process.env.LLM_API_KEY ?? "";
const LLM_MODEL = process.env.LLM_MODEL ?? "claude-sonnet-4-6";

const CODE_AND_DIAGRAM_RULE =
  " If any source code is written or projected, reproduce it verbatim inside a " +
  "fenced Markdown code block with a guessed language tag (```python, ```text, " +
  "etc.), preserving exact indentation — never paraphrase code. If there is a " +
  "diagram, flowchart, or tree, represent its structure as a small text outline " +
  "inside a fenced ```text block (one node per line, arrows as '->', indentation " +
  "for nesting) instead of prose.";

const PROMPTS: Record<string, string> = {
  board:
    "This is a photo of a lecture whiteboard/blackboard. Transcribe EXACTLY what " +
    "is written on it (text, formulas, labeled diagrams described briefly). " +
    "Preserve line structure. Do not add commentary or interpretation." +
    CODE_AND_DIAGRAM_RULE,
  slide:
    "This is a photo of a projected lecture slide. Transcribe its text content " +
    "exactly (title, bullets, formulas). Describe figures in one short bracketed " +
    "note each. No commentary." +
    CODE_AND_DIAGRAM_RULE,
  desk:
    "This is a photo of a lecturer showing something at their desk. Describe " +
    "briefly and factually what is being shown (object, screen content, action). " +
    "2-3 sentences maximum." +
    CODE_AND_DIAGRAM_RULE,
};

export type Extraction = { text: string; confidence: number };

/**
 * Extract text from a lecture frame. Returns null when the frame holds nothing
 * readable (the model answers EMPTY) or when the LLM is not configured.
 */
export async function extractFrameText(
  imageBase64: string,
  modality: "board" | "slide" | "desk",
): Promise<Extraction | null> {
  if (!LLM_KEY) throw new Error("LLM_API_KEY is not configured on the server");

  const resp = await fetch(`${LLM_BASE}/chat/completions`, {
    method: "POST",
    headers: { Authorization: `Bearer ${LLM_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      model: LLM_MODEL,
      max_tokens: 1200,
      messages: [
        {
          role: "system",
          content:
            PROMPTS[modality] +
            " If the image contains nothing readable or meaningful, reply with exactly: EMPTY",
        },
        {
          role: "user",
          content: [
            {
              type: "image_url",
              image_url: { url: `data:image/jpeg;base64,${imageBase64}` },
            },
          ],
        },
      ],
    }),
  });
  if (!resp.ok) throw new Error(`vision LLM ${resp.status}`);

  const data = await resp.json();
  const text: string = data?.choices?.[0]?.message?.content?.trim() ?? "";
  if (!text || text.toUpperCase() === "EMPTY") return null;
  // Vision transcription of handwriting is decent but not speech-grade.
  return { text, confidence: modality === "desk" ? 0.6 : 0.75 };
}
