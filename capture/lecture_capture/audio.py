"""Continuous microphone capture, delivered as fixed-length chunks.

A background PortAudio stream fills a queue so recording never stops while a
chunk is being transcribed — the gap-free capture the fusion engine assumes.
"""

from __future__ import annotations

import queue
from collections.abc import Iterator
from types import TracebackType

import numpy as np
import sounddevice as sd

from .config import SAMPLE_RATE


class MicStream:
    """Records continuously; yields ~`chunk_seconds` of mono float32 audio."""

    def __init__(self, chunk_seconds: float, device: int | None = None) -> None:
        self._q: queue.Queue[np.ndarray] = queue.Queue()
        self._chunk_samples = int(chunk_seconds * SAMPLE_RATE)
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
        """Yield concatenated audio once at least a chunk's worth has arrived."""
        buffer: list[np.ndarray] = []
        collected = 0
        while True:
            block = self._q.get()  # blocks until the mic delivers audio
            buffer.append(block)
            collected += len(block)
            if collected >= self._chunk_samples:
                yield np.concatenate(buffer)
                buffer, collected = [], 0
