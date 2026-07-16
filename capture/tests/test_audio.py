"""Unit tests for timestamped, bounded microphone capture."""

from datetime import datetime, timedelta, timezone

import numpy as np

from lecture_capture.audio import MicStream, UtteranceChunker

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
            min_speech_seconds=1.0,
            trailing_silence_seconds=0.5,
            max_utterance_seconds=4.0,
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

    def test_timed_chunk_keeps_first_speech_timestamp(self):
        chunker = UtteranceChunker(
            min_speech_seconds=0.2,
            trailing_silence_seconds=0.2,
        )
        base = datetime(2026, 7, 16, 10, 0, tzinfo=timezone.utc)
        output = None
        blocks = [silence_block()] + [speech_block()] * 3 + [silence_block()] * 3
        for index, block in enumerate(blocks):
            started = base + timedelta(seconds=index / 10)
            output = chunker.feed_timed(
                block, started, started + timedelta(seconds=0.1)
            )
            if output is not None:
                break
        assert output is not None
        assert output.started_at == base + timedelta(seconds=0.1)
        assert output.ended_at > output.started_at


def test_mic_queue_spools_overflow_to_wav_in_capture_order(tmp_path):
    mic = MicStream(
        max_utterance_seconds=4.0,
        memory_seconds=0.1,
        spool_directory=tmp_path,
    )
    samples_1 = np.full((BLOCK, 1), 0.1, np.float32)
    samples_2 = np.full((BLOCK, 1), 0.2, np.float32)
    mic._callback(samples_1, BLOCK, None, None)
    mic._callback(samples_2, BLOCK, None, None)

    assert mic._q.qsize() == 1
    assert len(list(tmp_path.glob("block_*.wav"))) == 1
    first = mic._next_block()
    second = mic._next_block()
    assert np.isclose(first.samples.mean(), 0.1)
    assert np.isclose(second.samples.mean(), 0.2, atol=1e-3)
    assert first.started_at <= second.started_at
