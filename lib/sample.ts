import type { EventIn } from "./types";

// A short multi-stream lecture moment used by the "seed demo" button.
const BASE = Date.parse("2026-01-01T09:00:00Z");
const at = (s: number) => new Date(BASE + s * 1000).toISOString();

export const SAMPLE_DOMAIN =
  "A university mathematics lecture. Group events into the concept being taught; " +
  "treat board content as the formal statement of what the lecturer says.";

export const SAMPLE_EVENTS: EventIn[] = [
  { timestamp: at(0), modality: "speech", content: "Today we're going to talk about derivatives.", confidence: 0.95 },
  { timestamp: at(1), modality: "slide", content: "Lecture 4 — Derivatives", confidence: 0.99 },
  { timestamp: at(3), modality: "speech", content: "Intuitively, the derivative measures the rate of change of a function.", confidence: 0.92 },
  { timestamp: at(5), modality: "board", content: "f'(x) = lim_{h->0} (f(x+h) - f(x)) / h", confidence: 0.99 },
  { timestamp: at(14), modality: "speech", content: "Okay, now let's work through this with a concrete example.", confidence: 0.9 },
  { timestamp: at(16), modality: "board", content: "f(x) = x^2", confidence: 0.99 },
  { timestamp: at(18), modality: "speech", content: "so the derivative here turns out to be two x.", confidence: 0.9 },
  { timestamp: at(20), modality: "board", content: "f'(x) = 2x", confidence: 0.99 },
];
