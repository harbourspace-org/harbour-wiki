"""Continuous microphone capture, delivered as speech utterances.

A background PortAudio stream fills a queue so recording never stops while a
chunk is being transcribed. On top of the raw blocks, :class:`UtteranceChunker`
cuts the stream at natural pauses (energy-based, adaptive to the room's noise
floor) instead of at a blind timer — so words are no longer sliced mid-sentence
and pure silence never reaches Whisper at all.

The chunker is pure state (no I/O) — see tests/test_audio.py.
"""

from __future__ import annotations

import queue
from collections.abc import Iterator
from types import TracebackType

import numpy as np
import sounddevice as sd

from .config import SAMPLE_RATE

# Utterance cutting (seconds).
MIN_SPEECH_SECONDS = 1.2  # don't emit micro-fragments
TRAILING_SILENCE_SECONDS = 0.8  # a pause this long ends the utterance
MAX_UTTERANCE_SECONDS = 12.0  # forced cut for a speaker who never pauses
MAX_SILENCE_BUFFER_SECONDS = 5.0  # discard accumulated silence (empty room)

# Energy gating.
_ABS_SPEECH_FLOOR = 0.006  # below this RMS nothing counts as speech
_FLOOR_MULTIPLIER = 3.0  # speech must rise this far above the noise floor
_FLOOR_EWMA = 0.05  # how fast the noise-floor estimate adapts


class UtteranceChunker:
    """Feed raw audio blocks; get whole utterances back at pause boundaries."""

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        min_speech_seconds: float = MIN_SPEECH_SECONDS,
        trailing_silence_seconds: float = TRAILING_SILENCE_SECONDS,
        max_utterance_seconds: float = MAX_UTTERANCE_SECONDS,
    ) -> None:
        self._rate = sample_rate
        self._min_speech = min_speech_seconds
        self._trailing_silence = trailing_silence_seconds
        self._max_samples = int(max_utterance_seconds * sample_rate)
        self._max_silence_samples = int(MAX_SILENCE_BUFFER_SECONDS * sample_rate)
        self._buffer: list[np.ndarray] = []
        self._buffered = 0
        self._speech_samples = 0
        self._silence_run = 0  # trailing-silence length in samples
        self._noise_floor = _ABS_SPEECH_FLOOR

    def _is_speech(self, block: np.ndarray) -> bool:
        rms = float(np.sqrt(np.mean(np.square(block)))) if block.size else 0.0
        threshold = max(_ABS_SPEECH_FLOOR, self._noise_floor * _FLOOR_MULTIPLIER)
        if rms < threshold:
            # Quiet block: let the noise-floor estimate adapt to the room.
            self._noise_floor = (1 - _FLOOR_EWMA) * self._noise_floor + _FLOOR_EWMA * max(
                rms, 1e-5
            )
            return False
        return True

    def feed(self, block: np.ndarray) -> np.ndarray | None:
        """Add one raw block; returns a finished utterance or None."""
        speech = self._is_speech(block)
        self._buffer.append(block)
        self._buffered += len(block)
        if speech:
            self._speech_samples += len(block)
            self._silence_run = 0
        else:
            self._silence_run += len(block)

        enough_speech = self._speech_samples >= int(self._min_speech * self._rate)
        paused = self._silence_run >= int(self._trailing_silence * self._rate)

        if enough_speech and paused:
            return self._cut()
        if self._buffered >= self._max_samples:
            # Forced cut mid-speech (or discard if it never contained speech).
            return self._cut() if enough_speech else self._reset()
        if self._speech_samples == 0 and self._buffered >= self._max_silence_samples:
            self._reset()  # empty room: don't hoard silence
        return None

    def _cut(self) -> np.ndarray:
        utterance = np.concatenate(self._buffer)
        self._reset()
        return utterance

    def _reset(self) -> None:
        self._buffer = []
        self._buffered = 0
        self._speech_samples = 0
        self._silence_run = 0


class MicStream:
    """Records continuously; yields utterances cut at natural pauses."""

    def __init__(self, max_utterance_seconds: float, device: int | None = None) -> None:
        self._q: queue.Queue[np.ndarray] = queue.Queue()
        self._chunker = UtteranceChunker(max_utterance_seconds=max_utterance_seconds)
        self._device = device
        self._stream: sd.InputStream | None = None

    def _callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:  # noqa: ANN001
        # PortAudio reuses `indata` after the callback returns, so copy first.
        self._q.put(indata[:, 0].copy())

    def __enter__(self) -> "MicStream":
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            device=self._device,
            callback=self._callback,
        )
        self._stream.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()

    def chunks(self) -> Iterator[np.ndarray]:
        """Yield one utterance at a time, cut at pauses (blocking)."""
        while True:
            block = self._q.get()  # blocks until the mic delivers audio
            utterance = self._chunker.feed(block)
            if utterance is not None:
                yield utterance
