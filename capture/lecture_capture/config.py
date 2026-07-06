"""Runtime configuration for the lecture capture client.

The operator announces only "class X is recording now" — Harbour.Wiki (the
single gateway to Knottra) decides which lecture that is, which session backs
it, and where the notes live. The recorder never holds the Knottra key; it
authenticates to the app with a capture token. Values come from CLI flags,
falling back to environment (and a local .env); secrets are never hard-coded.
"""

from __future__ import annotations

from dataclasses import dataclass

# faster-whisper expects 16 kHz mono float32 audio.
SAMPLE_RATE = 16_000

# small.en is a large accuracy jump over base.en on accented/noisy speech and
# still runs near-realtime on a modern laptop CPU with int8. Weak PC? tiny.en.
DEFAULT_MODEL = "small.en"
DEFAULT_CHUNK_SECONDS = 6.0


@dataclass(frozen=True)
class Config:
    """Immutable run configuration (see coding-style: no in-place mutation)."""

    base_url: str  # Harbour.Wiki base URL (the gateway)
    token: str | None  # capture Bearer token; may be empty for open/local dev
    class_id: str  # the course being recorded ("class X is recording now")
    class_title: str | None
    lecture_title: str | None
    force_new: bool  # start a new lecture even if one is resumable
    model_size: str
    chunk_seconds: float
    language: str | None
    device: int | None  # mic input-device index; None = system default
    context: str | None = None  # vocabulary hint fed to Whisper (initial_prompt)
    min_confidence: float = 0.35  # utterances below this are NOT sent

    @property
    def ingest_url(self) -> str:
        return f"{self.base_url}/api/ingest"
