"""Runtime configuration for the lecture capture client.

Values come from CLI flags, falling back to environment variables (and a local
.env). Secrets (the Knottra API key) are never hard-coded — they must be
supplied via env or flag.
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

    base_url: str
    api_key: str
    session_id: str
    domain_prompt: str
    model_size: str
    chunk_seconds: float
    language: str | None
    device: int | None  # mic input-device index; None = system default

    @property
    def events_url(self) -> str:
        return f"{self.base_url}/v1/sessions/{self.session_id}/events"

    @property
    def config_url(self) -> str:
        return f"{self.base_url}/v1/sessions/{self.session_id}/config"

    @property
    def flush_url(self) -> str:
        return f"{self.base_url}/v1/sessions/{self.session_id}/flush"
