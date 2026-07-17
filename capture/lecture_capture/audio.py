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
import hashlib
import os
import threading
import wave
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import TracebackType

import numpy as np
import sounddevice as sd

from .config import SAMPLE_RATE

# Utterance cutting (seconds).
MIN_SPEECH_SECONDS = 1.2  # don't emit micro-fragments
TRAILING_SILENCE_SECONDS = 0.8  # a pause this long ends the utterance
MAX_UTTERANCE_SECONDS = 12.0  # forced cut for a speaker who never pauses
MAX_SILENCE_BUFFER_SECONDS = 5.0  # discard accumulated silence (empty room)

# Energy gating. Calibrated against real laptop mics at default input volume:
# speech ≈ 0.005–0.015 RMS, room silence ≈ 0.001–0.003 (measured on a MacBook).
_ABS_SPEECH_FLOOR = 0.003  # below this RMS nothing counts as speech
_FLOOR_MULTIPLIER = 2.0  # speech must rise this far above the noise floor
_FLOOR_CEILING = 0.003  # noise-floor estimate may never creep into speech range
_FLOOR_EWMA = 0.05  # how fast the noise-floor estimate adapts

# Auto-gain for quiet mics/rooms: some hardware (e.g. a conference speakerphone
# at low input level) produces real speech only slightly above
# _ABS_SPEECH_FLOOR, too close to reliably clear the noise-floor multiplier.
# Boost each block toward a target RMS before the speech gate ever sees it.
_AUTO_GAIN_TARGET_RMS = 0.02
_AUTO_GAIN_MAX = 12.0  # cap so near-silence isn't amplified into noise

MIC_BLOCK_SECONDS = 0.1
MIC_MEMORY_SECONDS = 30.0


@dataclass(frozen=True)
class AudioBlock:
    samples: np.ndarray
    started_at: datetime
    ended_at: datetime


@dataclass(frozen=True)
class AudioChunk:
    """An utterance with wall-clock bounds measured while recording."""

    samples: np.ndarray
    started_at: datetime
    ended_at: datetime


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
        self._speech_started_at: datetime | None = None
        self._last_ended_at: datetime | None = None

    @staticmethod
    def _auto_gain(block: np.ndarray) -> np.ndarray:
        """Boost a quiet block toward the target RMS before anything else sees
        it — some hardware (e.g. a conference speakerphone at low input
        level) otherwise produces speech too close to the noise-floor gate
        to ever be recognized as speech at all."""
        if block.size == 0:
            return block
        rms = float(np.sqrt(np.mean(np.square(block))))
        if rms < 1e-6 or rms >= _AUTO_GAIN_TARGET_RMS:
            return block
        gain = min(_AUTO_GAIN_MAX, _AUTO_GAIN_TARGET_RMS / rms)
        return np.clip(block * gain, -1.0, 1.0)

    def _is_speech(self, block: np.ndarray) -> bool:
        rms = float(np.sqrt(np.mean(np.square(block)))) if block.size else 0.0
        threshold = max(_ABS_SPEECH_FLOOR, self._noise_floor * _FLOOR_MULTIPLIER)
        if rms < threshold:
            # Quiet block: let the noise-floor estimate adapt to the room,
            # but never so far up that quiet speech starts reading as noise.
            adapted = (1 - _FLOOR_EWMA) * self._noise_floor + _FLOOR_EWMA * max(
                rms, 1e-5
            )
            self._noise_floor = min(adapted, _FLOOR_CEILING)
            return False
        return True

    def feed(self, block: np.ndarray) -> np.ndarray | None:
        """Add one raw block; returns a finished utterance or None."""
        result = self._feed(block, None, None)
        return result[0] if result is not None else None

    def feed_timed(
        self,
        block: np.ndarray,
        started_at: datetime,
        ended_at: datetime,
    ) -> AudioChunk | None:
        """Timed equivalent of :meth:`feed`, used by the live microphone."""
        result = self._feed(block, started_at, ended_at)
        if result is None:
            return None
        samples, speech_started_at, utterance_ended_at = result
        return AudioChunk(
            samples,
            speech_started_at or started_at,
            utterance_ended_at or ended_at,
        )

    def _feed(
        self,
        block: np.ndarray,
        started_at: datetime | None,
        ended_at: datetime | None,
    ) -> tuple[np.ndarray, datetime | None, datetime | None] | None:
        block = self._auto_gain(block)
        speech = self._is_speech(block)
        self._buffer.append(block)
        self._buffered += len(block)
        if ended_at is not None:
            self._last_ended_at = ended_at
        if speech:
            if self._speech_started_at is None and started_at is not None:
                self._speech_started_at = started_at
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

    def _cut(self) -> tuple[np.ndarray, datetime | None, datetime | None]:
        utterance = np.concatenate(self._buffer)
        bounds = self._speech_started_at, self._last_ended_at
        self._reset()
        return utterance, *bounds

    def _reset(self) -> None:
        self._buffer = []
        self._buffered = 0
        self._speech_samples = 0
        self._silence_run = 0
        self._speech_started_at = None
        self._last_ended_at = None


class _DiskAudioSpool:
    """Overflow storage for microphone blocks, ordered by capture time.

    Files are standard mono PCM WAVs so an interrupted lecture leaves
    inspectable/recoverable audio rather than an opaque temporary blob.
    """

    def __init__(
        self,
        directory: str | Path | None = None,
        spool_key: str | None = None,
    ) -> None:
        configured = os.getenv("LECTURE_AUDIO_SPOOL_DIR")
        root = (
            Path(directory)
            if directory is not None
            else Path(configured)
            if configured
            else Path.home() / ".lecture-capture" / "audio-spool"
        )
        self.directory = (
            root / hashlib.sha256(spool_key.encode()).hexdigest()[:20]
            if spool_key
            else root
        )
        self.directory.mkdir(parents=True, exist_ok=True)
        self._counter = 0

    def has_items(self) -> bool:
        return next(self.directory.glob("block_*.wav"), None) is not None

    def put(self, block: AudioBlock) -> None:
        self._counter += 1
        start_ns = int(block.started_at.timestamp() * 1_000_000_000)
        path = (
            self.directory
            / f"block_{start_ns:020d}_{os.getpid()}_{self._counter:09d}.wav"
        )
        tmp = path.with_suffix(".tmp")
        pcm = np.clip(block.samples, -1.0, 1.0)
        pcm = (pcm * 32767.0).astype("<i2")
        with wave.open(str(tmp), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(SAMPLE_RATE)
            out.writeframes(pcm.tobytes())
        tmp.replace(path)

    def pop(self) -> AudioBlock | None:
        paths = sorted(self.directory.glob("block_*.wav"))
        if not paths:
            return None
        path = paths[0]
        start_ns = int(path.stem.split("_")[1])
        with wave.open(str(path), "rb") as source:
            frames = source.readframes(source.getnframes())
            samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32767.0
            duration = len(samples) / source.getframerate()
        path.unlink(missing_ok=True)
        started_at = datetime.fromtimestamp(start_ns / 1_000_000_000, tz=timezone.utc)
        return AudioBlock(samples, started_at, started_at + timedelta(seconds=duration))


class MicStream:
    """Records continuously; yields utterances cut at natural pauses."""

    def __init__(
        self,
        max_utterance_seconds: float,
        device: int | None = None,
        *,
        memory_seconds: float = MIC_MEMORY_SECONDS,
        spool_directory: str | Path | None = None,
        spool_key: str | None = None,
    ) -> None:
        max_blocks = max(1, int(memory_seconds / MIC_BLOCK_SECONDS))
        self._q: queue.Queue[AudioBlock] = queue.Queue(maxsize=max_blocks)
        self._chunker = UtteranceChunker(max_utterance_seconds=max_utterance_seconds)
        self._device = device
        self._stream: sd.InputStream | None = None
        self._spool = _DiskAudioSpool(spool_directory, spool_key)
        self._spool_lock = threading.Lock()
        # If a previous process left recoverable blocks, preserve ordering by
        # putting all new blocks behind them until the spool is drained.
        self._spooling = self._spool.has_items()
        self._overflow_blocks = 0

    def _callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:  # noqa: ANN001
        # PortAudio reuses `indata` after the callback returns, so copy first.
        ended_at = datetime.now(timezone.utc)
        started_at = ended_at - timedelta(seconds=frames / SAMPLE_RATE)
        block = AudioBlock(indata[:, 0].copy(), started_at, ended_at)
        with self._spool_lock:
            if not self._spooling:
                try:
                    self._q.put_nowait(block)
                    return
                except queue.Full:
                    self._spooling = True
                    print(
                        "[capture] transcription is behind — spooling microphone audio to disk",
                        flush=True,
                    )
            self._spool.put(block)
            self._overflow_blocks += 1

    def __enter__(self) -> "MicStream":
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            device=self._device,
            blocksize=int(SAMPLE_RATE * MIC_BLOCK_SECONDS),
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

    def _next_block(self) -> AudioBlock:
        while True:
            try:
                return self._q.get(timeout=0.2)
            except queue.Empty:
                with self._spool_lock:
                    block = self._spool.pop()
                    if block is not None:
                        return block
                    self._spooling = False

    def chunks(self) -> Iterator[AudioChunk]:
        """Yield one utterance at a time, cut at pauses (blocking)."""
        while True:
            block = self._next_block()
            utterance = self._chunker.feed_timed(
                block.samples,
                block.started_at,
                block.ended_at,
            )
            if utterance is not None:
                yield utterance
