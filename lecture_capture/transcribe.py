"""Local speech-to-text via faster-whisper — offline, no API key.

Tuned for a hard environment (distant/cheap lecture-room mics):
- beam search + a vocabulary hint (``initial_prompt``) for accuracy;
- ``condition_on_previous_text=False`` so one bad chunk can't poison the next;
- per-segment quality gates that DROP Whisper's classic hallucinations
  (text invented over noise/silence, repetition loops) instead of shipping
  them into the record.

The gates are pure functions (see tests/test_transcribe.py).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# Standard Whisper hallucination heuristics (same family OpenAI uses).
MAX_NO_SPEECH_PROB = 0.5  # segment is probably silence/noise
MIN_AVG_LOGPROB = -1.0  # model was guessing
MAX_COMPRESSION_RATIO = 2.4  # repetition loops compress suspiciously well


@dataclass(frozen=True)
class Transcript:
    text: str
    confidence: float


@dataclass(frozen=True)
class SegmentStats:
    """The quality numbers faster-whisper reports per segment."""

    text: str
    avg_logprob: float
    no_speech_prob: float
    compression_ratio: float


def keep_segment(seg: SegmentStats) -> bool:
    """True if a segment looks like real speech rather than a hallucination."""
    if not seg.text.strip():
        return False
    if seg.no_speech_prob > MAX_NO_SPEECH_PROB:
        return False
    if seg.avg_logprob < MIN_AVG_LOGPROB:
        return False
    if seg.compression_ratio > MAX_COMPRESSION_RATIO:
        return False
    return True


def confidence_from_logprobs(logprobs: list[float]) -> float:
    """Map Whisper's average log-probability (<= 0) into Knottra's [0, 1]."""
    if not logprobs:
        return 0.0
    avg = sum(logprobs) / len(logprobs)
    return max(0.0, min(1.0, math.exp(avg)))


def normalize_audio(audio: np.ndarray, target_peak: float = 0.9) -> np.ndarray:
    """Peak-normalize quiet audio (distant mic) so Whisper gets usable levels.

    Near-silence is returned untouched — amplifying the noise floor of an
    empty room only feeds the hallucination gates more work.
    """
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak < 1e-3 or peak >= target_peak:
        return audio
    return (audio * (target_peak / peak)).astype(np.float32)


class Transcriber:
    def __init__(
        self,
        model_size: str,
        language: str | None,
        context: str | None = None,
    ) -> None:
        # Heavy import kept local so `--help` and config errors stay instant.
        from faster_whisper import WhisperModel

        self._model = WhisperModel(model_size, device="cpu", compute_type="int8")
        self._language = language
        # Vocabulary bias: course/lecture topic words dramatically help
        # domain terms survive a noisy signal.
        self._context = (context or "").strip() or None

    def transcribe(self, audio: np.ndarray) -> Transcript:
        segments, _info = self._model.transcribe(
            normalize_audio(audio),
            language=self._language,
            vad_filter=True,  # drop silence so we don't emit empty events
            beam_size=5,  # beam search: noticeably better than greedy on noisy audio
            condition_on_previous_text=False,  # one bad chunk can't poison the next
            initial_prompt=self._context,
        )
        parts: list[str] = []
        logprobs: list[float] = []
        for seg in segments:
            stats = SegmentStats(
                text=seg.text,
                avg_logprob=seg.avg_logprob,
                no_speech_prob=seg.no_speech_prob,
                compression_ratio=seg.compression_ratio,
            )
            if not keep_segment(stats):
                continue
            parts.append(seg.text.strip())
            logprobs.append(seg.avg_logprob)
        return Transcript(
            text=" ".join(parts).strip(),
            confidence=confidence_from_logprobs(logprobs),
        )
