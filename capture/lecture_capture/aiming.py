"""Autonomous aiming: find the board/screen in the frame and keep it framed.

The layers, separated for testability:

- :class:`LLMAimDetector` — the aiming brain: ships a small screenshot to
  Harbour.Wiki's ``/api/aim``, where Claude looks at the room and returns the
  target's bbox. This is what actually UNDERSTANDS "that rectangle is the
  whiteboard, the other one is the projector". Used while scouting/aiming.
- :func:`detect_target` — classical CV fallback and cheap drift-watch: the
  largest bright, roughly-rectangular region. No network; runs every poll
  while locked so we notice the target moving/vanishing without LLM calls.
- :class:`AimController` — a PURE feedback controller (no camera, no clock):
  given the detected bbox each observation, it emits per-axis step directions
  (pan/tilt/zoom) until the target is centered and fills the frame. It learns
  each motor's sign convention from how the bbox actually moves (UVC cameras
  disagree), and freezes an axis that makes no progress (missing motor).
- :func:`crop_to_bbox` — digital framing: even with no PTZ motors at all,
  shipped frames are cropped to the detected target, which is what actually
  makes handwriting legible to the fusion model.
"""

from __future__ import annotations

from base64 import b64encode
from dataclasses import dataclass, field

import cv2
import numpy as np

# Detection tuning.
_MIN_AREA_FRAC = 0.04  # target must cover ≥4% of the frame
_MAX_AREA_FRAC = 0.90  # a near-whole-frame "target" is uniform light/noise,
#                        not a board — and carries no aiming information anyway
_MIN_RECT_FILL = 0.55  # contour area / bounding-rect area — rectangular-ish
_ASPECT_RANGE = (0.6, 5.0)  # w/h of boards and 16:9 / 4:3 screens

# Control tuning.
_CENTER_DEADBAND = 0.08  # |center error| below this (frame fraction) = centered
_FILL_TARGET = 0.60  # target width as a fraction of frame width
_FILL_DEADBAND = 0.12
_MAX_MISSES = 8  # consecutive detection misses before the target is "lost"
_MAX_FLIPS = 3  # sign flips per axis before we conclude the axis is broken
_MAX_STALLS = 6  # moves with no error improvement before freezing the axis
_DONE_STREAK = 2  # consecutive in-band observations to settle


Bbox = tuple[int, int, int, int]  # x, y, w, h


def detect_target(frame_bgr: np.ndarray) -> Bbox | None:
    """Locate the board / projected screen: the largest bright, mostly-
    rectangular region. Returns (x, y, w, h) in pixels, or None."""
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (9, 9), 0)
    mean, std = float(gray.mean()), float(gray.std())
    threshold = min(235.0, mean + 0.6 * std)
    _, mask = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    frame_area = frame_bgr.shape[0] * frame_bgr.shape[1]
    best: Bbox | None = None
    best_area = 0.0
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < _MIN_AREA_FRAC * frame_area:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        if w * h > _MAX_AREA_FRAC * frame_area:
            continue
        if h == 0 or not (_ASPECT_RANGE[0] <= w / h <= _ASPECT_RANGE[1]):
            continue
        if area / (w * h) < _MIN_RECT_FILL:
            continue
        if area > best_area:
            best, best_area = (x, y, w, h), area
    return best


_PERSON_CLASS = 0  # COCO class id
_yolo_model = None  # lazy-loaded singleton — loading YOLO per call would be far too slow


def _get_yolo_model():
    global _yolo_model
    if _yolo_model is None:
        from ultralytics import YOLO

        _yolo_model = YOLO("yolov8n.pt")
    return _yolo_model


def detect_person(frame_bgr: np.ndarray) -> Bbox | None:
    """Locate the largest detected person — the local, cheap detector for
    ``--modality desk`` (tracks the teacher). Runs YOLOv8n locally; never
    calls the vision LLM for positioning, only for content description
    downstream in Knottra. Returns (x, y, w, h) in pixels, or None."""
    model = _get_yolo_model()
    results = model.predict(frame_bgr, verbose=False, classes=[_PERSON_CLASS])
    best: Bbox | None = None
    best_area = 0.0
    for result in results:
        for box in result.boxes:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            area = (x2 - x1) * (y2 - y1)
            if area > best_area:
                best_area = area
                best = (int(x1), int(y1), int(x2 - x1), int(y2 - y1))
    return best


def crop_to_bbox(frame: np.ndarray, bbox: Bbox, margin: float = 0.08) -> np.ndarray:
    """Crop to the bbox plus a relative margin, clamped to the frame."""
    fh, fw = frame.shape[:2]
    x, y, w, h = bbox
    mx, my = int(w * margin), int(h * margin)
    x0, y0 = max(0, x - mx), max(0, y - my)
    x1, y1 = min(fw, x + w + mx), min(fh, y + h + my)
    if x1 <= x0 or y1 <= y0:
        return frame
    return frame[y0:y1, x0:x1]


_AIM_SHOT_WIDTH = 640  # aim screenshots are small: cheap, fast, good enough
_AIM_SHOT_QUALITY = 60


def encode_aim_shot(frame: np.ndarray) -> str:
    """Downscaled JPEG base64 of the frame, sized for /api/aim calls."""
    h, w = frame.shape[:2]
    if w > _AIM_SHOT_WIDTH:
        frame = cv2.resize(frame, (_AIM_SHOT_WIDTH, int(h * _AIM_SHOT_WIDTH / w)))
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, _AIM_SHOT_QUALITY])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return b64encode(buf.tobytes()).decode()


class LLMAimDetector:
    """Locate the target by asking the server's LLM (Claude) via /api/aim.

    ``locate_target(image_b64, target) -> dict`` is injected (the Gateway
    method in production; a stub in tests). Network/LLM failures return None —
    the caller falls back to classical CV rather than crashing the recorder.
    """

    def __init__(self, locate_target, target: str) -> None:
        self._locate = locate_target
        self._target = target

    def locate(self, frame: np.ndarray) -> Bbox | None:
        try:
            result = self._locate(encode_aim_shot(frame), self._target)
        except Exception as error:  # noqa: BLE001 — aiming must never kill capture
            print(f"[camera] aim query failed: {error}", flush=True)
            return None
        if not result.get("found") or not result.get("bbox"):
            return None
        fh, fw = frame.shape[:2]
        nx, ny, nw, nh = (float(v) for v in result["bbox"])
        x, y = int(nx * fw), int(ny * fh)
        w, h = int(nw * fw), int(nh * fh)
        if w < 4 or h < 4:
            return None
        return (max(0, x), max(0, y), min(w, fw - x), min(h, fh - y))


@dataclass
class _Axis:
    """Per-axis controller state: learned sign + progress tracking."""

    sign: float = 1.0
    prev_error: float | None = None
    moved_last: bool = False
    flips: int = 0
    stalls: int = 0

    @property
    def alive(self) -> bool:
        return self.flips <= _MAX_FLIPS and self.stalls <= _MAX_STALLS

    def step(self, error: float, deadband: float) -> float:
        """Direction (+1/-1 scaled by learned sign) to reduce ``error``; 0 if
        in-band or the axis has been written off."""
        if self.moved_last and self.prev_error is not None:
            improved = abs(error) < abs(self.prev_error) - 1e-3
            if not improved:
                if abs(error) > abs(self.prev_error) + 1e-3:
                    self.sign = -self.sign  # we drove it the wrong way
                    self.flips += 1
                else:
                    self.stalls += 1  # no effect at all (motor missing/at limit)
            else:
                self.stalls = 0
        self.prev_error = error

        if abs(error) <= deadband or not self.alive:
            self.moved_last = False
            return 0.0
        self.moved_last = True
        return -self.sign if error > 0 else self.sign


@dataclass
class AimCommand:
    pan: float = 0.0  # step direction: -1 / 0 / +1 (caller scales to hardware)
    tilt: float = 0.0
    zoom: float = 0.0
    settled: bool = False  # target framed — stop moving, start shipping
    lost: bool = False  # target not seen for a while — zoom out / re-scout

    @property
    def moving(self) -> bool:
        return bool(self.pan or self.tilt or self.zoom)


@dataclass
class AimController:
    """Pure feedback loop: bbox observations in, step directions out."""

    fill_target: float = _FILL_TARGET
    _pan: _Axis = field(default_factory=_Axis)
    _tilt: _Axis = field(default_factory=_Axis)
    _zoom: _Axis = field(default_factory=_Axis)
    _misses: int = 0
    _in_band_streak: int = 0

    def observe(self, bbox: Bbox | None, frame_w: int, frame_h: int) -> AimCommand:
        if bbox is None:
            self._misses += 1
            self._in_band_streak = 0
            return AimCommand(lost=self._misses >= _MAX_MISSES)
        self._misses = 0

        x, y, w, h = bbox
        center_x_err = (x + w / 2) / frame_w - 0.5
        center_y_err = (y + h / 2) / frame_h - 0.5
        # Positive fill error = too small → zoom in (axis sign learning still
        # applies, so an inverted zoom control self-corrects).
        fill_err = self.fill_target - (w / frame_w)
        # Never zoom in past the frame edge: an edge-touching bbox means the
        # target is already partially out of view.
        touches_edge = x <= 2 or y <= 2 or x + w >= frame_w - 2 or y + h >= frame_h - 2
        if touches_edge and fill_err > 0:
            fill_err = 0.0

        command = AimCommand(
            pan=self._pan.step(center_x_err, _CENTER_DEADBAND),
            tilt=self._tilt.step(center_y_err, _CENTER_DEADBAND),
            # step() reduces positive error with -sign; zoom error is inverted
            # (positive = need MORE zoom), so feed it negated.
            zoom=self._zoom.step(-fill_err, _FILL_DEADBAND),
        )
        if not command.moving:
            self._in_band_streak += 1
        else:
            self._in_band_streak = 0
        command.settled = self._in_band_streak >= _DONE_STREAK
        return command

    def reset(self) -> None:
        """Forget convergence state (e.g. after a re-scout) but KEEP the
        learned motor signs — those are properties of the hardware."""
        self._misses = 0
        self._in_band_streak = 0
        for axis in (self._pan, self._tilt, self._zoom):
            axis.prev_error = None
            axis.moved_last = False
            axis.stalls = 0
