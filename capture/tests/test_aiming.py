"""Unit tests for autonomous aiming — pure logic, no camera, no motors.

The detector is fed synthetic room frames (dark room, bright board); the
controller is fed scripted bbox sequences simulating how a camera responds
to its own commands, including a camera with an inverted pan motor and one
with no motors at all.
"""

import numpy as np

from lecture_capture.aiming import (
    AimController,
    crop_to_bbox,
    detect_target,
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
    assert out.shape[0] == 330 and out.shape[1] == 440  # clamped at 0, extended right/down


def test_crop_center_region():
    frame = room_with_board(300, 200, 400, 300)
    out = crop_to_bbox(frame, (300, 200, 400, 300), margin=0.0)
    assert out.shape[:2] == (300, 400)
    assert out.mean() > 200  # it's the bright board, not the dark room


# --------------------------------------------------------------------------- #
# AimController — convergence
# --------------------------------------------------------------------------- #
def simulate(controller: AimController, x: float, w: float, steps: int = 60,
             pan_gain: float = 0.04, zoom_gain: float = 0.05):
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
        last = controller.observe((int(0.1 * W), int(0.1 * H), int(0.2 * W), int(0.2 * H)), W, H)
    assert not last.moving  # every axis written off after repeated stalls


def test_lost_after_consecutive_misses_and_recovers():
    controller = AimController()
    lost = None
    for _ in range(10):
        lost = controller.observe(None, W, H)
    assert lost.lost
    controller.reset()
    cmd = controller.observe((int(0.4 * W), int(0.35 * H), int(0.25 * W), int(0.25 * H)), W, H)
    assert not cmd.lost  # re-scouted target picked up again


def test_edge_touching_target_does_not_zoom_in_further():
    controller = AimController()
    # Big target already touching the left edge: zooming in would cut it off.
    cmd = controller.observe((0, int(0.2 * H), int(0.4 * W), int(0.5 * H)), W, H)
    assert cmd.zoom <= 0
