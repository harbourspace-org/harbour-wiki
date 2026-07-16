"""Unit tests for the camera agent's pure decision core.

No camera, no clock, no network — SnapshotPolicy is driven with synthetic
frames and explicit timestamps, exactly the seams it was designed around.
"""

import base64
import threading
import time
from datetime import datetime, timezone

import numpy as np

from lecture_capture.camera import (
    BestBoardFrame,
    BoardSnapshot,
    FrameAnalysisWorker,
    PeriodicSnapshotPolicy,
    SnapshotUploadWorker,
    SnapshotPolicy,
    encode_jpeg_b64,
    make_test_board,
    mean_diff,
    motion_centroid_x,
    privacy_board_crop,
    privacy_semantic_scout,
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
        assert (
            policy.observe(with_content(), now=3.0) is False
        )  # teacher writes → motion
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


class TestPeriodicSnapshotPolicy:
    def test_first_frame_is_due_then_every_ten_seconds(self):
        policy = PeriodicSnapshotPolicy(interval_seconds=10.0)
        assert policy.due(100.0)
        policy.mark_sent(100.0)
        assert not policy.due(109.99)
        assert policy.due(110.0)

    def test_failed_send_remains_due(self):
        policy = PeriodicSnapshotPolicy(interval_seconds=10.0)
        assert policy.due(5.0)
        assert policy.due(5.1)  # no mark_sent after a failed request


def test_best_board_frame_prefers_unoccluded_view():
    board = (100, 100, 500, 300)
    sharp = np.zeros((720, 1280, 3), np.uint8)
    sharp[100:400, 100:600] = make_test_board()[100:400, 100:600]
    buffer = BestBoardFrame()
    first_at = datetime(2026, 7, 16, 10, 0, tzinfo=timezone.utc)
    buffer.offer(
        sharp,
        board,
        [(150, 120, 400, 280)],
        first_at,
    )  # lecturer obscures most of it

    clear = sharp.copy()
    clear[130:370:20, 120:580] = 255  # extra crisp board detail, no obstruction
    captured_at = datetime(2026, 7, 16, 10, 0, 9, tzinfo=timezone.utc)
    buffer.offer(clear, board, [], captured_at)
    picked = buffer.peek()
    assert picked is not None
    assert picked.captured_at == captured_at
    assert np.array_equal(picked.frame, clear[85:415, 75:625])


def test_board_upload_fails_closed_without_confirmed_bbox():
    frame = make_test_board()
    buffer = BestBoardFrame()
    captured_at = datetime(2026, 7, 16, 10, 0, tzinfo=timezone.utc)
    assert not buffer.offer(frame, None, [], captured_at)
    assert buffer.peek() is None
    assert privacy_board_crop(frame, None, []) is None


def test_privacy_crop_masks_person_inside_board():
    frame = make_test_board()
    board = (40, 40, 900, 500)
    person = (200, 100, 180, 300)
    unmasked = privacy_board_crop(frame, board, [])
    masked = privacy_board_crop(frame, board, [person])
    assert unmasked is not None and masked is not None
    assert masked.shape == unmasked.shape
    assert not np.array_equal(masked, unmasked)


def test_semantic_scout_masks_foreground_but_keeps_teacher_zone():
    frame = make_test_board()
    rng = np.random.default_rng(9)
    frame[430:710, 100:500] = rng.integers(0, 255, size=(280, 400, 3), dtype=np.uint8)
    foreground_student = (100, 430, 400, 280)
    teacher = (800, 120, 120, 320)
    protected = privacy_semantic_scout(frame, [foreground_student, teacher])
    assert not np.array_equal(protected[430:710, 100:500], frame[430:710, 100:500])
    assert np.array_equal(protected[120:440, 800:920], frame[120:440, 800:920])


def test_upload_worker_preserves_capture_timestamp():
    calls = []

    def fake_send(image_b64, captured_at):
        calls.append((image_b64, captured_at))
        return {"ingested": 1}

    captured_at = datetime(2026, 7, 16, 10, 0, 7, tzinfo=timezone.utc)
    worker = SnapshotUploadWorker(fake_send)
    worker.submit(BoardSnapshot(make_test_board(), captured_at, 1.0))
    worker.close()
    assert worker.sent == 1
    assert calls[0][1] == captured_at


def test_analysis_worker_keeps_latest_frame_without_blocking_submit(monkeypatch):
    from lecture_capture import aiming

    first_started = threading.Event()
    release_first = threading.Event()

    def fake_detect_target(frame):
        if int(frame[0, 0, 0]) == 1:
            first_started.set()
            release_first.wait(timeout=1.0)
        return (10, 10, 100, 60)

    monkeypatch.setattr(aiming, "detect_target", fake_detect_target)
    monkeypatch.setattr(aiming, "detect_people", lambda frame: [])

    worker = FrameAnalysisWorker(follow_teacher=False, modality="board")
    captured_at = datetime(2026, 7, 16, 10, 0, tzinfo=timezone.utc)
    first = np.full((90, 160, 3), 1, np.uint8)
    second = np.full((90, 160, 3), 2, np.uint8)
    worker.submit(
        frame_seq=1,
        frame=first,
        captured_at=captured_at,
        observed_at=1.0,
        allow_semantic=True,
    )
    assert first_started.wait(timeout=1.0)
    worker.submit(
        frame_seq=2,
        frame=second,
        captured_at=captured_at,
        observed_at=2.0,
        allow_semantic=True,
    )
    release_first.set()

    deadline = time.monotonic() + 1.0
    result = None
    while time.monotonic() < deadline:
        result = worker.poll(after_frame_seq=1)
        if result is not None:
            break
        time.sleep(0.01)
    worker.close()
    assert result is not None
    assert result.frame_seq == 2
    assert int(result.frame[0, 0, 0]) == 2
