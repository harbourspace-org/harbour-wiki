// Camera-aiming brain: Claude looks at a room screenshot and says where the
// board / projection screen is. Used by the capture agent's --auto-aim loop
// (scout wide → locate → move → screenshot → re-locate …). Lives here so the
// lecture PC never holds an LLM key — same single-gateway rule as everything.

import { z } from "zod";

const LLM_BASE = process.env.LLM_BASE_URL ?? "https://opencode.ai/zen/v1";
const LLM_KEY = process.env.LLM_API_KEY ?? "";
const LLM_MODEL = process.env.LLM_MODEL ?? "claude-sonnet-4-6";

const TARGETS: Record<string, string> = {
  board:
    "the physical whiteboard or blackboard — the writing surface itself, not a " +
    "projection screen and not a TV",
  slide:
    "the projection screen or large display showing slides — the projected/" +
    "displayed image area, not a whiteboard",
  desk: "the lecturer's desk / demo table area",
};

const resultSchema = z.object({
  found: z.boolean(),
  // Normalized to the image: x, y = top-left corner, w, h — all in 0..1.
  bbox: z.tuple([z.number(), z.number(), z.number(), z.number()]).nullable(),
  confidence: z.number().min(0).max(1).catch(0.5),
});

export type AimResult = z.infer<typeof resultSchema>;

const clamp01 = (v: number) => Math.max(0, Math.min(1, v));

/**
 * Locate `target` in a room frame. Returns found=false when the target is not
 * visible (the agent should zoom out / re-scout). Throws on LLM failure —
 * the caller decides whether to fall back to local detection.
 */
export async function locateTarget(
  imageBase64: string,
  target: "board" | "slide" | "desk",
): Promise<AimResult> {
  if (!LLM_KEY) throw new Error("LLM_API_KEY is not configured on the server");

  const resp = await fetch(`${LLM_BASE}/chat/completions`, {
    method: "POST",
    headers: { Authorization: `Bearer ${LLM_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      model: LLM_MODEL,
      max_tokens: 200,
      messages: [
        {
          role: "system",
          content:
            "You aim a lecture-room camera. Locate " +
            TARGETS[target] +
            " in the image. Reply with STRICT JSON only, no prose, no code fence: " +
            '{"found": boolean, "bbox": [x, y, w, h] | null, "confidence": 0..1}. ' +
            "bbox is the target's bounding box normalized to the image (x,y = " +
            "top-left corner, all values 0..1). If the target is not visible or " +
            "you are unsure which object it is, return found=false and bbox=null.",
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
  if (!resp.ok) throw new Error(`aim LLM ${resp.status}`);

  const data = await resp.json();
  const text: string = data?.choices?.[0]?.message?.content?.trim() ?? "";
  // Tolerate a stray code fence despite the instruction.
  const jsonText = text.replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "");
  const parsed = resultSchema.safeParse(JSON.parse(jsonText));
  if (!parsed.success) throw new Error(`aim LLM returned unexpected shape: ${text.slice(0, 200)}`);

  const result = parsed.data;
  if (!result.found || !result.bbox) return { found: false, bbox: null, confidence: 0 };
  const [x, y, w, h] = result.bbox.map(clamp01);
  if (w < 0.02 || h < 0.02) return { found: false, bbox: null, confidence: 0 };
  return { found: true, bbox: [x, y, Math.min(w, 1 - x), Math.min(h, 1 - y)], confidence: result.confidence };
}
