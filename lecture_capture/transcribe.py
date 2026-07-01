"""Local speech-to-text via faster-whisper — offline, no API key.

The model downloads once on first run and is cached; int8 on CPU keeps a
lecture-grade model close to real time on a laptop.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Transcript:
    text: str
    confidence: float


class Transcriber:
    def __init__(self, model_size: str, language: str | None) -> None:
        # Heavy import kept local so `--help` and config errors stay instant.
        from faster_whisper import WhisperModel

        self._model = WhisperModel(model_size, device="cpu", compute_type="int8")
        self._language = language

    def transcribe(self, audio: np.ndarray) -> Transcript:
        segments, _info = self._model.transcribe(
            audio,
            language=self._language,
            vad_filter=True,  # drop silence so we don't emit empty events
            beam_size=1,
        )
        parts: list[str] = []
        logprobs: list[float] = []
        for seg in segments:
            text = seg.text.strip()
            if text:
                parts.append(text)
                logprobs.append(seg.avg_logprob)
        return Transcript(
            text=" ".join(parts).strip(),
            confidence=_confidence_from_logprobs(logprobs),
        )


def _confidence_from_logprobs(logprobs: list[float]) -> float:
    """Map Whisper's average log-probability (<= 0) into Knottra's [0, 1]."""
    if not logprobs:
        return 0.0
    avg = sum(logprobs) / len(logprobs)
    return max(0.0, min(1.0, math.exp(avg)))
