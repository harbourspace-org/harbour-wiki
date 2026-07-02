"""Unit tests for the camera agent's pure decision core.

No camera, no clock, no network — SnapshotPolicy is driven with synthetic
frames and explicit timestamps, exactly the seams it was designed around.
"""

import base64

import numpy as np
import pytest

from lecture_capture.camera import (
    SnapshotPolicy,
    encode_jpeg_b64,
    make_test_board,
    mean_diff,
    motion_centroid_x,
    small_gray,
)


def blank(level: int = 200) -> np.ndarray:
    return np.full((90, 160), level, np.uint8)


def with_content(level: int = 200) -> np.ndarray:
    frame = blank(level)
    frame[20:70, 30:130] = 60  # a big dark "written" block
    return frame


class TestSnapshotPolicy:
    def test_holds_until_scene_is_stable(self):
        policy = SnapshotPolicy(stable_seconds=3.0, min_send_seconds=0.0)
        # First frame: no baseline → counts as motion → hold.
        assert policy.observe(blank(), now=0.0) is False
        # Identical frames, but the stability window hasn't elapsed yet.
        assert policy.observe(blank(), now=1.0) is False
        assert policy.observe(blank(), now=2.0) is False
        # 3s of calm reached → ship.
        assert policy.observe(blank(), now=4.5) is True

    def test_motion_resets_the_stability_timer(self):
        policy = SnapshotPolicy(stable_seconds=3.0, min_send_seconds=0.0)
        policy.observe(blank(), now=0.0)
        policy.observe(blank(), now=2.5)  # almost stable…
        assert policy.observe(with_content(), now=3.0) is False  # teacher writes → motion
        # Calm resumes at 5.0 — the timer restarts THERE, so stable at 8.0+.
        assert policy.observe(with_content(), now=5.0) is False
        assert policy.observe(with_content(), now=6.5) is False
        assert policy.observe(with_content(), now=8.5) is True

    def test_never_reships_unchanged_content(self):
        policy = SnapshotPolicy(stable_seconds=1.0, min_send_seconds=0.0)
        policy.observe(with_content(), now=0.0)  # no baseline yet -> "motion"
        policy.observe(with_content(), now=0.5)  # calm confirmed; timer starts
        assert policy.observe(with_content(), now=2.0) is True
        policy.mark_sent(with_content(), now=2.0)
        # Board unchanged forever after → never ship again.
        for t in (5.0, 50.0, 500.0):
            assert policy.observe(with_content(), now=t) is False

    def test_ships_again_when_the_board_changes(self):
        policy = SnapshotPolicy(stable_seconds=1.0, min_send_seconds=0.0)
        policy.observe(blank(), now=0.0)
        policy.observe(blank(), now=0.5)
        assert policy.observe(blank(), now=2.0) is True
        policy.mark_sent(blank(), now=2.0)
        # New writing appears (one motion frame), then the scene calms down.
        assert policy.observe(with_content(), now=3.0) is False  # motion
        assert policy.observe(with_content(), now=3.5) is False  # calming…
        assert policy.observe(with_content(), now=5.0) is True  # stable + fresh

    def test_cooldown_blocks_rapid_fire(self):
        policy = SnapshotPolicy(stable_seconds=1.0, min_send_seconds=30.0)
        policy.observe(blank(), now=0.0)
        policy.observe(blank(), now=0.5)
        assert policy.observe(blank(), now=2.0) is True
        policy.mark_sent(blank(), now=2.0)
        # Fresh content, fully stable — but inside the 30s cooldown.
        policy.observe(with_content(), now=4.0)  # motion frame
        assert policy.observe(with_content(), now=10.0) is False  # cooled=False
        assert policy.observe(with_content(), now=33.0) is True  # cooldown over

    def test_failed_send_is_retried(self):
        # observe() saying "ship" without mark_sent (send failed) → next stable
        # observation still says "ship".
        policy = SnapshotPolicy(stable_seconds=1.0, min_send_seconds=0.0)
        policy.observe(blank(), now=0.0)
        policy.observe(blank(), now=0.5)
        assert policy.observe(blank(), now=2.0) is True  # send attempt #1 (fails)
        assert policy.observe(blank(), now=3.0) is True  # retried


class TestImageHelpers:
    def test_mean_diff_none_baseline_is_max(self):
        assert mean_diff(None, blank()) == 255.0

    def test_mean_diff_identical_is_zero(self):
        assert mean_diff(blank(), blank()) == 0.0

    def test_motion_centroid_finds_the_side(self):
        prev = blank()
        cur = blank()
        cur[:, 120:160] = 0  # motion on the RIGHT quarter
        cx = motion_centroid_x(prev, cur)
        assert cx is not None and cx > 0.6

    def test_motion_centroid_none_when_calm(self):
        assert motion_centroid_x(blank(), blank()) is None

    def test_encode_jpeg_b64_is_valid_and_bounded(self):
        b64 = encode_jpeg_b64(make_test_board())
        raw = base64.b64decode(b64)
        assert raw[:2] == b"\xff\xd8"  # JPEG magic
        assert len(b64) < 6_000_000  # under the server's limit

    def test_small_gray_shape(self):
        assert small_gray(make_test_board()).shape == (90, 160)
