"""Unit tests for the utterance chunker (pure state, synthetic blocks)."""

import numpy as np

from lecture_capture.audio import UtteranceChunker

RATE = 16_000
BLOCK = RATE // 10  # 100ms blocks


def speech_block() -> np.ndarray:
    rng = np.random.default_rng(7)
    return (0.2 * rng.standard_normal(BLOCK)).astype(np.float32)


def silence_block() -> np.ndarray:
    return np.zeros(BLOCK, np.float32)


def feed_many(chunker, blocks):
    outputs = []
    for b in blocks:
        out = chunker.feed(b)
        if out is not None:
            outputs.append(out)
    return outputs


class TestUtteranceChunker:
    def test_cuts_at_pause_after_speech(self):
        chunker = UtteranceChunker(min_speech_seconds=1.0, trailing_silence_seconds=0.5)
        # 2s of speech then 1s of silence → exactly one utterance.
        blocks = [speech_block()] * 20 + [silence_block()] * 10
        outputs = feed_many(chunker, blocks)
        assert len(outputs) == 1
        # The utterance contains the speech (~2s) plus the trailing pause.
        assert len(outputs[0]) >= 2 * RATE

    def test_no_cut_while_still_talking(self):
        chunker = UtteranceChunker(min_speech_seconds=1.0, trailing_silence_seconds=0.5)
        assert feed_many(chunker, [speech_block()] * 30) == []  # 3s, no pause yet

    def test_forced_cut_on_endless_speech(self):
        chunker = UtteranceChunker(
            min_speech_seconds=1.0, trailing_silence_seconds=0.5, max_utterance_seconds=4.0
        )
        outputs = feed_many(chunker, [speech_block()] * 100)  # 10s of nonstop talk
        assert len(outputs) >= 2  # cut every ~4s

    def test_pure_silence_never_emits(self):
        chunker = UtteranceChunker(min_speech_seconds=1.0, trailing_silence_seconds=0.5)
        assert feed_many(chunker, [silence_block()] * 200) == []  # 20s empty room

    def test_micro_fragment_not_emitted_alone(self):
        chunker = UtteranceChunker(min_speech_seconds=1.5, trailing_silence_seconds=0.5)
        # 0.5s cough then silence: below min speech → nothing emitted.
        outputs = feed_many(chunker, [speech_block()] * 5 + [silence_block()] * 20)
        assert outputs == []
