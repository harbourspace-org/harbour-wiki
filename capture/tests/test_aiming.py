"""Unit tests for autonomous aiming — pure logic, no camera, no motors.

The detector is fed synthetic room frames (dark room, bright board); the
controller is fed scripted bbox sequences simulating how a camera responds
to its own commands, including a camera with an inverted pan motor and one
with no motors at all.
"""

import numpy as np

from lecture_capture.aiming import (
    AimController,
    LLMAimDetector,
    PersonDetection,
    TeacherTracker,
    crop_to_bbox,
    detect_target,
    encode_aim_shot,
    select_teacher_candidate,
)

W, H = 1280, 720


def room_with_board(x: int, y: int, w: int, h: int) -> np.ndarray:
    """A dark room with one bright board-like rectangle."""
    frame = np.full((H, W, 3), 40, np.uint8)
    frame[y : y + h, x : x + w] = 230
    return frame


# --------------------------------------------------------------------------- #
# detect_target
# --------------------------------------------------------------------------- #
def test_detects_bright_board_bbox():
    bbox = detect_target(room_with_board(300, 200, 500, 280))
    assert bbox is not None
    x, y, w, h = bbox
    assert abs(x - 300) < 30 and abs(y - 200) < 30
    assert abs(w - 500) < 60 and abs(h - 280) < 60


def test_no_target_in_empty_room():
    frame = np.full((H, W, 3), 40, np.uint8)
    rng = np.random.default_rng(7)
    noise = rng.integers(0, 25, size=frame.shape, dtype=np.uint8)
    assert detect_target(frame + noise) is None


def test_ignores_small_and_extreme_aspect_regions():
    frame = np.full((H, W, 3), 40, np.uint8)
    frame[100:130, 100:150] = 230  # too small (< 4% of frame)
    frame[300:310, 100:1100] = 230  # a strip light: aspect way beyond 5.0
    assert detect_target(frame) is None


def test_picks_the_largest_candidate():
    frame = np.full((H, W, 3), 40, np.uint8)
    frame[100:250, 80:330] = 230  # small screen
    frame[300:640, 400:1100] = 230  # the actual board
    x, y, w, h = detect_target(frame)
    assert x > 350 and w > 500


# --------------------------------------------------------------------------- #
# crop_to_bbox
# --------------------------------------------------------------------------- #
def test_crop_adds_margin_and_clamps_to_frame():
    frame = room_with_board(0, 0, 400, 300)  # bbox at the corner
    out = crop_to_bbox(frame, (0, 0, 400, 300), margin=0.1)
    assert (
        out.shape[0] == 330 and out.shape[1] == 440
    )  # clamped at 0, extended right/down


def test_crop_center_region():
    frame = room_with_board(300, 200, 400, 300)
    out = crop_to_bbox(frame, (300, 200, 400, 300), margin=0.0)
    assert out.shape[:2] == (300, 400)
    assert out.mean() > 200  # it's the bright board, not the dark room


# --------------------------------------------------------------------------- #
# AimController — convergence
# --------------------------------------------------------------------------- #
def simulate(
    controller: AimController,
    x: float,
    w: float,
    steps: int = 60,
    pan_gain: float = 0.04,
    zoom_gain: float = 0.05,
):
    """1-D room simulator: the camera pans (moves bbox opposite to command)
    and zooms (grows bbox width). Returns (x, w, settled_at)."""
    settled_at = None
    for i in range(steps):
        bbox = (int(x * W), int(0.3 * H), int(w * W), int(0.3 * H))
        cmd = controller.observe(bbox, W, H)
        if cmd.settled and settled_at is None:
            settled_at = i
            break
        # Panning right (+) moves the VIEW right → target slides LEFT in frame.
        x -= cmd.pan * pan_gain
        # Zooming in (+) magnifies around the center.
        if cmd.zoom:
            scale = 1 + cmd.zoom * zoom_gain
            center = x + w / 2
            w *= scale
            x = (center - 0.5) * scale + 0.5 - w / 2
        x = max(0.0, min(1.0 - w, x))
    return x, w, settled_at


def test_converges_on_offcenter_small_target():
    x, w, settled_at = simulate(AimController(), x=0.05, w=0.20)
    assert settled_at is not None, "controller never settled"
    assert abs((x + w / 2) - 0.5) <= 0.10  # centered
    assert w >= 0.45  # zoomed in toward the fill target


def test_converges_with_inverted_pan_motor():
    # Same room, but the pan motor runs backwards: the controller must learn
    # the sign from the bbox's response and still converge.
    x, w, settled_at = simulate(AimController(), x=0.65, w=0.25, pan_gain=-0.04)
    assert settled_at is not None
    assert abs((x + w / 2) - 0.5) <= 0.10


def test_dead_motors_freeze_axes_and_settle_never_diverges():
    # No motors: bbox never responds. Axes must stall out (not oscillate
    # forever); the command goes quiet so digital-crop shipping can proceed.
    controller = AimController()
    last = None
    for _ in range(40):
        last = controller.observe(
            (int(0.1 * W), int(0.1 * H), int(0.2 * W), int(0.2 * H)), W, H
        )
    assert not last.moving  # every axis written off after repeated stalls


def test_lost_after_consecutive_misses_and_recovers():
    controller = AimController()
    lost = None
    for _ in range(10):
        lost = controller.observe(None, W, H)
    assert lost.lost
    controller.reset()
    cmd = controller.observe(
        (int(0.4 * W), int(0.35 * H), int(0.25 * W), int(0.25 * H)), W, H
    )
    assert not cmd.lost  # re-scouted target picked up again


def test_edge_touching_target_does_not_zoom_in_further():
    controller = AimController()
    # Big target already touching the left edge: zooming in would cut it off.
    cmd = controller.observe((0, int(0.2 * H), int(0.4 * W), int(0.5 * H)), W, H)
    assert cmd.zoom <= 0


# --------------------------------------------------------------------------- #
# LLMAimDetector — the Claude-backed detector (gateway stubbed)
# --------------------------------------------------------------------------- #
def test_llm_detector_converts_normalized_bbox_to_pixels():
    calls = []

    def fake_locate(image_b64, target):
        calls.append((image_b64, target))
        return {"found": True, "bbox": [0.25, 0.25, 0.5, 0.4], "confidence": 0.9}

    detector = LLMAimDetector(fake_locate, "board")
    bbox = detector.locate(room_with_board(300, 200, 500, 280))
    assert bbox == (320, 180, 640, 288)  # 0.25*1280, 0.25*720, 0.5*1280, 0.4*720
    assert calls[0][1] == "board"
    assert len(calls[0][0]) > 100  # a real base64 JPEG went out


def test_llm_detector_not_found_and_failure_return_none():
    detector = LLMAimDetector(lambda i, t: {"found": False, "bbox": None}, "slide")
    assert detector.locate(room_with_board(0, 0, 400, 300)) is None

    def boom(i, t):
        raise RuntimeError("network down")

    assert LLMAimDetector(boom, "slide").locate(room_with_board(0, 0, 400, 300)) is None


def test_llm_teacher_detector_rejects_low_confidence_guess():
    detector = LLMAimDetector(
        lambda i, t: {"found": True, "bbox": [0.2, 0.2, 0.2, 0.5], "confidence": 0.4},
        "teacher",
        min_confidence=0.65,
    )
    assert detector.locate(room_with_board(0, 0, 400, 300)) is None


def test_aim_shot_is_downscaled():
    import base64

    shot = base64.b64decode(encode_aim_shot(room_with_board(300, 200, 500, 280)))
    import cv2

    decoded = cv2.imdecode(np.frombuffer(shot, np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape[1] == 640  # width capped for cheap LLM calls


# --------------------------------------------------------------------------- #
# Teacher selection — never follow seated foreground students
# --------------------------------------------------------------------------- #
def test_teacher_selector_rejects_large_foreground_student():
    board = (180, 80, 850, 390)
    people = [
        PersonDetection(
            (40, 350, 500, 360), 0.97
        ),  # large seated pupil, back to camera
        PersonDetection((690, 150, 120, 300), 0.82),  # standing lecturer at the board
    ]
    assert select_teacher_candidate(people, W, H, board_bbox=board) == people[1].bbox


def test_teacher_selector_fails_closed_when_only_audience_visible():
    board = (180, 60, 850, 330)
    people = [
        PersonDetection((20, 420, 420, 290), 0.98),
        PersonDetection((700, 430, 360, 280), 0.96),
    ]
    assert select_teacher_candidate(people, W, H, board_bbox=board) is None


def test_teacher_selector_does_not_guess_without_board_or_semantic_seed():
    plausible_but_unanchored = [PersonDetection((500, 180, 130, 300), 0.99)]
    assert select_teacher_candidate(plausible_but_unanchored, W, H) is None


def test_teacher_tracker_prefers_temporal_continuity():
    tracker = TeacherTracker()
    board = (100, 70, 1000, 430)
    first = PersonDetection((250, 130, 120, 300), 0.85)
    assert tracker.select([first], W, H, board) == first.bbox

    same_teacher = PersonDetection((285, 130, 120, 300), 0.75)
    passer_by = PersonDetection((760, 120, 130, 310), 0.99)
    assert tracker.select([same_teacher, passer_by], W, H, board) == same_teacher.bbox


def test_semantic_seed_overrides_a_wrong_local_board_candidate():
    tracker = TeacherTracker()
    semantic_teacher = (850, 130, 120, 300)
    tracker.seed(semantic_teacher)
    wrong_bright_rectangle = (80, 80, 380, 260)
    yolo_match = PersonDetection((860, 135, 120, 300), 0.8)
    assert tracker.select([yolo_match], W, H, wrong_bright_rectangle) == yolo_match.bbox
