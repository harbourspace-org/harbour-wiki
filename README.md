# Harbour.Wiki

**The auto-built, living wiki of everything taught at Harbour.Space.**

Harbour.Wiki is the student-facing app. It turns lectures into a structured,
concept-linked, askable knowledge base — so a student can catch up on a class
they missed and ask questions grounded in what was actually taught.

## How it fits together

```
Capture + transcription/OCR   (lecture audio, board, slides → text events)
        │
        ▼
   Knottra  ── the fusion engine (separate repo: ../knottra) ──
   weaves the unsynchronized streams into a structured record
   (concepts · sub-points · logical links) and serves it back
        │
        ▼
Harbour.Wiki  (this repo)
   • renders the record as a navigable per-course wiki
   • answers student questions with its own LLM, grounded in
     Knottra's structured slices (Knottra returns DATA, not answers)
```

Knottra is the engine (infrastructure); Harbour.Wiki is the product students
use. This repo consumes Knottra's API — it does **not** reimplement fusion.

## Status

Greenfield. The Knottra engine it builds on is production-ready (see
`../knottra`). App stack and UI to be decided.

## Related

- `../knottra` — the multi-stream temporal context fusion engine (the core).
