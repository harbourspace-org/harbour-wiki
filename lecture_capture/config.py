"""Runtime configuration for the lecture capture client.

The recorder talks ONLY to Harbour.Wiki (the single gateway to Knottra) — it
never holds the Knottra API key. It authenticates to the app with a capture
token. Values come from CLI flags, falling back to environment (and a local
.env); secrets are never hard-coded.
"""

from __future__ import annotations

from dataclasses import dataclass

# faster-whisper expects 16 kHz mono float32 audio.
SAMPLE_RATE = 16_000

DEFAULT_MODEL = "base.en"
DEFAULT_CHUNK_SECONDS = 6.0
DEFAULT_DOMAIN_PROMPT = (
    "This is a university lecture. Group the speech into the concepts being "
    "taught, each with its sub-points and the logical flow between concepts."
)


@dataclass(frozen=True)
class Config:
    """Immutable run configuration (see coding-style: no in-place mutation)."""

    base_url: str  # Harbour.Wiki base URL (the gateway)
    token: str | None  # capture Bearer token; may be empty for open/local dev
    session_id: str
    domain_prompt: str
    course_id: str  # registers the lecture in the wiki course index (MCP search)
    course_title: str
    label: str
    model_size: str
    chunk_seconds: float
    language: str | None
    device: int | None  # mic input-device index; None = system default

    @property
    def ingest_url(self) -> str:
        return f"{self.base_url}/api/ingest"
