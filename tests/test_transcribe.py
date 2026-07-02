"""Unit tests for the transcription quality gates (pure functions)."""

import numpy as np

from lecture_capture.transcribe import (
    SegmentStats,
    confidence_from_logprobs,
    keep_segment,
    normalize_audio,
)


def seg(**overrides) -> SegmentStats:
    base = dict(text="a real sentence", avg_logprob=-0.3, no_speech_prob=0.1, compression_ratio=1.4)
    base.update(overrides)
    return SegmentStats(**base)


class TestKeepSegment:
    def test_good_speech_passes(self):
        assert keep_segment(seg()) is True

    def test_probable_silence_dropped(self):
        # Whisper hallucinating over silence: high no_speech_prob.
        assert keep_segment(seg(no_speech_prob=0.8)) is False

    def test_guessing_dropped(self):
        # The "Berlin Wall" failure: fluent text with terrible logprob.
        assert keep_segment(seg(avg_logprob=-1.4)) is False

    def test_repetition_loop_dropped(self):
        assert keep_segment(seg(compression_ratio=3.1)) is False

    def test_empty_text_dropped(self):
        assert keep_segment(seg(text="   ")) is False


class TestConfidence:
    def test_empty_is_zero(self):
        assert confidence_from_logprobs([]) == 0.0

    def test_good_logprob_high(self):
        assert confidence_from_logprobs([-0.1]) > 0.85

    def test_bad_logprob_low(self):
        assert confidence_from_logprobs([-1.0]) < 0.4


class TestNormalize:
    def test_quiet_audio_is_amplified(self):
        quiet = np.full(1600, 0.05, np.float32)
        out = normalize_audio(quiet)
        assert float(np.max(np.abs(out))) > 0.8

    def test_loud_audio_untouched(self):
        loud = np.full(1600, 0.95, np.float32)
        assert np.array_equal(normalize_audio(loud), loud)

    def test_near_silence_not_amplified(self):
        # Boosting an empty room's noise floor would feed hallucinations.
        silence = np.full(1600, 0.0005, np.float32)
        assert np.array_equal(normalize_audio(silence), silence)
