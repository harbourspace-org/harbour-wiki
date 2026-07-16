"""Camera agent: watch the lecture room, ship NEW board content as an image.

The loop mirrors how a human note-taker photographs a whiteboard: during each
10-second interval retain the sharpest view with the least teacher occlusion,
then send it to Harbour.Wiki's /api/vision. The app forwards it AS AN IMAGE into
the same Knottra session the audio feeds, so the fusion model reads the board
beside whatever speech happened at that moment.

Cadence, privacy cropping, frame ranking, analysis, and upload backpressure are
separate testable components (see tests/test_camera.py).

PTZ: the Windows DirectShow session owns the Logitech PTZ Pro 2 once, follows a
semantically acquired teacher with local YOLO, and can republish that same
physical stream as a virtual camera for Zoom.
"""

from __future__ import annotations

import base64
import platform
import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import cv2
import numpy as np

# Tuned for lecture rooms: calm scene for a few seconds = teacher stepped away.
STABLE_SECONDS = 3.0
MOTION_THRESHOLD = 4.0  # mean |diff| on the downsampled gray view
CHANGE_THRESHOLD = 6.0  # how different from the LAST SENT frame counts as new
SEND_MAX_WIDTH = 1280
JPEG_QUALITY = 70

NormalizedPolygon = tuple[tuple[float, float], ...]
DEFAULT_AUDIENCE_ZONES: tuple[NormalizedPolygon, ...] = (
    ((0.0, 0.62), (1.0, 0.62), (1.0, 1.0), (0.0, 1.0)),
)
PRIVACY_MIN_PERSON_CONFIDENCE = 0.35


@dataclass(frozen=True)
class CameraOptions:
    device: int
    modality: str  # board | slide | desk
    poll_seconds: float
    min_send_seconds: float
    track: bool
    preview: bool
    pan: float | None
    tilt: float | None
    zoom: float | None
    auto_aim: bool = False  # find the board/screen and frame it autonomously
    flip_180: bool = False  # camera physically mounted upside down
    follow_teacher: bool = (
        False  # track the lecturer near the board, never the audience
    )
    lost_delay_seconds: float = 1.5
    share_with_zoom: bool = (
        False  # publish our single physical capture as a virtual camera
    )
    pan_sign: int = 1
    tilt_sign: int = 1
    audience_zones: tuple[NormalizedPolygon, ...] = DEFAULT_AUDIENCE_ZONES
    privacy_min_person_confidence: float = PRIVACY_MIN_PERSON_CONFIDENCE


# --------------------------------------------------------------------------- #
# Pure decision core (unit-tested; no camera, no clock, no network)
# --------------------------------------------------------------------------- #
class SnapshotPolicy:
    """Decides, observation by observation, when to ship a frame.

    Ship when ALL hold:
      stable — no motion for ``stable_seconds`` (nobody writing/occluding);
      fresh  — view differs from the LAST SENT frame (new content);
      cooled — at least ``min_send_seconds`` since the previous send.
    """

    def __init__(
        self,
        stable_seconds: float = STABLE_SECONDS,
        min_send_seconds: float = 20.0,
        motion_threshold: float = MOTION_THRESHOLD,
        change_threshold: float = CHANGE_THRESHOLD,
    ) -> None:
        self._stable_seconds = stable_seconds
        self._min_send_seconds = min_send_seconds
        self._motion_threshold = motion_threshold
        self._change_threshold = change_threshold
        self._prev: np.ndarray | None = None
        self._last_sent: np.ndarray | None = None
        self._stable_since: float | None = None
        self._last_sent_at: float = float("-inf")

    def observe(self, gray_small: np.ndarray, now: float) -> bool:
        """Feed one downsampled gray frame; True means "ship this frame now"."""
        motion = mean_diff(self._prev, gray_small)
        self._prev = gray_small
        if motion > self._motion_threshold:
            self._stable_since = None
            return False
        if self._stable_since is None:
            self._stable_since = now

        stable = now - self._stable_since >= self._stable_seconds
        fresh = mean_diff(self._last_sent, gray_small) > self._change_threshold
        cooled = now - self._last_sent_at >= self._min_send_seconds
        return stable and fresh and cooled

    def mark_sent(self, gray_small: np.ndarray, now: float) -> None:
        """Record a successful send (failed sends are NOT marked → retried)."""
        self._last_sent = gray_small
        self._last_sent_at = now


class PeriodicSnapshotPolicy:
    """A strict capture/enqueue cadence for the live board stream.

    HTTP retries belong to :class:`SnapshotUploadWorker`; scheduling remains
    independent of network latency. The old stable/changed policy is retained
    above for callers that want it, but live capture uses periodic context for
    every 10-second speech window.
    """

    def __init__(self, interval_seconds: float = 10.0) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self._interval = interval_seconds
        self._last_sent_at = float("-inf")

    def due(self, now: float) -> bool:
        return now - self._last_sent_at >= self._interval

    def mark_sent(self, now: float) -> None:
        self._last_sent_at = now


# --------------------------------------------------------------------------- #
# Image helpers (pure)
# --------------------------------------------------------------------------- #
def small_gray(frame: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (160, 90))
    return cv2.GaussianBlur(small, (5, 5), 0)


def mean_diff(a: np.ndarray | None, b: np.ndarray) -> float:
    """Mean absolute difference; a missing baseline counts as maximal change."""
    if a is None:
        return 255.0
    return float(np.mean(cv2.absdiff(a, b)))


def motion_centroid_x(prev: np.ndarray, cur: np.ndarray) -> float | None:
    """Normalized x (0..1) of where motion happens; None if scene is calm."""
    diff = cv2.threshold(cv2.absdiff(prev, cur), 18, 255, cv2.THRESH_BINARY)[1]
    moments = cv2.moments(diff)
    if moments["m00"] < 1000:  # too little motion to mean anything
        return None
    return (moments["m10"] / moments["m00"]) / diff.shape[1]


def encode_jpeg_b64(frame: np.ndarray) -> str:
    h, w = frame.shape[:2]
    if w > SEND_MAX_WIDTH:
        frame = cv2.resize(frame, (SEND_MAX_WIDTH, int(h * SEND_MAX_WIDTH / w)))
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return base64.b64encode(buf.tobytes()).decode()


def _bbox_overlap_fraction(
    a: tuple[int, int, int, int] | None, b: tuple[int, int, int, int] | None
) -> float:
    """Fraction of ``b`` obscured by ``a`` (teacher over writing surface)."""
    if a is None or b is None:
        return 0.0
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x0, y0 = max(ax, bx), max(ay, by)
    x1, y1 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    intersection = max(0, x1 - x0) * max(0, y1 - y0)
    return intersection / max(1, bw * bh)


@dataclass(frozen=True)
class BoardSnapshot:
    """A privacy-filtered board crop bound to its actual capture time."""

    frame: np.ndarray
    captured_at: datetime
    score: float
    image_b64: str | None = None


def _board_crop_bounds(
    frame: np.ndarray,
    board_bbox: tuple[int, int, int, int],
    margin: float = 0.05,
) -> tuple[int, int, int, int] | None:
    frame_h, frame_w = frame.shape[:2]
    x, y, w, h = board_bbox
    if w <= 0 or h <= 0:
        return None
    mx, my = int(w * margin), int(h * margin)
    x0, y0 = max(0, x - mx), max(0, y - my)
    x1, y1 = min(frame_w, x + w + mx), min(frame_h, y + h + my)
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def _anonymize_region(image: np.ndarray, x0: int, y0: int, x1: int, y1: int) -> None:
    roi = image[y0:y1, x0:x1]
    if roi.size == 0:
        return
    tiny_w = max(1, min(10, roi.shape[1] // 12))
    tiny_h = max(1, min(10, roi.shape[0] // 12))
    pixelated = cv2.resize(roi, (tiny_w, tiny_h), interpolation=cv2.INTER_AREA)
    pixelated = cv2.resize(
        pixelated, (roi.shape[1], roi.shape[0]), interpolation=cv2.INTER_NEAREST
    )
    max_kernel = min(15, roi.shape[0], roi.shape[1])
    kernel = max_kernel if max_kernel % 2 == 1 else max_kernel - 1
    if kernel >= 3:
        pixelated = cv2.GaussianBlur(pixelated, (kernel, kernel), 0)
    image[y0:y1, x0:x1] = pixelated


def _person_parts(person) -> tuple[tuple[int, int, int, int], float, np.ndarray | None]:
    """Accept both PersonDetection and legacy bbox tuples in pure tests."""
    if hasattr(person, "bbox"):
        return person.bbox, float(person.confidence), getattr(person, "mask", None)
    return person, 1.0, None


def _zone_mask(
    frame_shape: tuple[int, ...], zones: tuple[NormalizedPolygon, ...]
) -> np.ndarray:
    height, width = frame_shape[:2]
    mask = np.zeros((height, width), np.uint8)
    for zone in zones:
        if len(zone) < 3:
            continue
        points = np.array(
            [
                (
                    round(max(0.0, min(1.0, x)) * (width - 1)),
                    round(max(0.0, min(1.0, y)) * (height - 1)),
                )
                for x, y in zone
            ],
            dtype=np.int32,
        )
        cv2.fillPoly(mask, [points], 255)
    return mask


def _anonymize_mask(image: np.ndarray, mask: np.ndarray) -> None:
    ys, xs = np.where(mask > 0)
    if not len(xs):
        return
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    original = image.copy()
    _anonymize_region(image, x0, y0, x1, y1)
    # Keep legible board pixels outside the dilated person silhouette.
    image[mask == 0] = original[mask == 0]


_face_cascade = None


def _blur_detected_faces(image: np.ndarray) -> None:
    """Supplement person segmentation with OpenCV's local face detector."""
    global _face_cascade
    cascade_type = getattr(cv2, "CascadeClassifier", None)
    data = getattr(cv2, "data", None)
    if cascade_type is None or data is None:
        # OpenCV 5 preview wheels omit the legacy cascade API. Person
        # segmentation + the hard audience polygon remain mandatory.
        return
    if _face_cascade is None:
        path = data.haarcascades + "haarcascade_frontalface_default.xml"
        _face_cascade = cascade_type(path)
    if _face_cascade.empty():
        return
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    for x, y, width, height in _face_cascade.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=4, minSize=(20, 20)
    ):
        margin_x, margin_y = int(width * 0.25), int(height * 0.35)
        _anonymize_region(
            image,
            max(0, x - margin_x),
            max(0, y - margin_y),
            min(image.shape[1], x + width + margin_x),
            min(image.shape[0], y + height + margin_y),
        )


def privacy_semantic_scout(
    frame: np.ndarray,
    people: list,
    audience_zones: tuple[NormalizedPolygon, ...] = DEFAULT_AUDIENCE_ZONES,
) -> np.ndarray:
    """Mask seated/foreground people before a room image reaches the aim LLM."""
    protected = frame.copy()
    frame_h, frame_w = protected.shape[:2]
    # This is independent of person detection: even a missed student in the
    # calibrated desk area cannot reach the semantic service.
    protected[_zone_mask(protected.shape, audience_zones) > 0] = 127
    for person in people:
        (x, y, width, height), _, mask = _person_parts(person)
        cy = (y + height / 2) / frame_h
        bottom = (y + height) / frame_h
        is_foreground = cy > 0.64 or bottom > 0.88 or width / frame_w > 0.48
        if not is_foreground:
            continue
        if mask is not None and mask.shape == (frame_h, frame_w):
            expanded = cv2.dilate(mask.astype(np.uint8), np.ones((15, 15), np.uint8))
            _anonymize_mask(protected, expanded)
            continue
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(frame_w, x + width), min(frame_h, y + height)
        _anonymize_region(protected, x0, y0, x1, y1)
    return protected


def privacy_board_crop(
    frame: np.ndarray,
    board_bbox: tuple[int, int, int, int] | None,
    people: list,
    audience_zones: tuple[NormalizedPolygon, ...] = DEFAULT_AUDIENCE_ZONES,
    min_person_confidence: float = PRIVACY_MIN_PERSON_CONFIDENCE,
) -> np.ndarray | None:
    """Return only the confirmed board, heavily anonymizing intersecting people.

    Fail closed: without a valid board bbox no pixels leave the lecture PC.
    Full-room fallback images can contain identifiable students and are never
    acceptable for the ``board`` stream.
    """
    if board_bbox is None:
        return None
    bounds = _board_crop_bounds(frame, board_bbox)
    if bounds is None:
        return None
    x0, y0, x1, y1 = bounds
    cropped = frame[y0:y1, x0:x1].copy()

    # Mask the calibrated desk/audience geometry even when YOLO misses a
    # person entirely. This is intentionally destructive and fail-safe.
    forbidden = _zone_mask(frame.shape, audience_zones)[y0:y1, x0:x1]
    cropped[forbidden > 0] = 127

    for person in people:
        (px, py, pw, ph), confidence, mask = _person_parts(person)
        ix0, iy0 = max(x0, px), max(y0, py)
        ix1, iy1 = min(x1, px + pw), min(y1, py + ph)
        if ix1 <= ix0 or iy1 <= iy0:
            continue
        # A weak overlapping detection means "possibly a person". Refusing
        # the whole upload is safer than trusting a noisy silhouette.
        if confidence < min_person_confidence:
            return None
        rx0, ry0 = ix0 - x0, iy0 - y0
        rx1, ry1 = ix1 - x0, iy1 - y0
        if mask is not None and mask.shape == frame.shape[:2]:
            person_mask = mask[y0:y1, x0:x1].astype(np.uint8)
            person_mask = cv2.dilate(person_mask, np.ones((15, 15), np.uint8))
            _anonymize_mask(cropped, person_mask)
        else:
            # Conservative fallback for detectors without segmentation.
            _anonymize_region(cropped, rx0, ry0, rx1, ry1)
    _blur_detected_faces(cropped)
    return cropped


def joint_framing_bbox(
    teacher_bbox: tuple[int, int, int, int] | None,
    board_bbox: tuple[int, int, int, int] | None,
    frame_w: int,
    frame_h: int,
    padding: float = 0.04,
) -> tuple[int, int, int, int] | None:
    """Union the lecturer and board; require both before moving the camera."""
    if teacher_bbox is None or board_bbox is None:
        return None
    tx, ty, tw, th = teacher_bbox
    bx, by, bw, bh = board_bbox
    x0, y0 = min(tx, bx), min(ty, by)
    x1, y1 = max(tx + tw, bx + bw), max(ty + th, by + bh)
    pad_x, pad_y = int((x1 - x0) * padding), int((y1 - y0) * padding)
    x0, y0 = max(0, x0 - pad_x), max(0, y0 - pad_y)
    x1, y1 = min(frame_w, x1 + pad_x), min(frame_h, y1 + pad_y)
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1 - x0, y1 - y0


class BestBoardFrame:
    """Keep the best recent privacy-filtered board view for one interval."""

    def __init__(
        self,
        *,
        audience_zones: tuple[NormalizedPolygon, ...] = DEFAULT_AUDIENCE_ZONES,
        min_person_confidence: float = PRIVACY_MIN_PERSON_CONFIDENCE,
    ) -> None:
        self._snapshot: BoardSnapshot | None = None
        self._audience_zones = audience_zones
        self._min_person_confidence = min_person_confidence

    def offer(
        self,
        frame: np.ndarray,
        board_bbox: tuple[int, int, int, int] | None,
        people: list,
        captured_at: datetime,
    ) -> bool:
        out = privacy_board_crop(
            frame,
            board_bbox,
            people,
            self._audience_zones,
            self._min_person_confidence,
        )
        if out is None:
            return False
        gray = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
        sharpness = min(2500.0, float(cv2.Laplacian(gray, cv2.CV_64F).var()))
        occlusion = min(
            1.0,
            sum(
                _bbox_overlap_fraction(_person_parts(person)[0], board_bbox)
                for person in people
            ),
        )
        score = sharpness - 1800.0 * occlusion
        # A modest recency bias prevents an extremely sharp frame from the
        # beginning of the interval beating newly written content at the end.
        if self._snapshot is not None:
            age = max(0.0, (captured_at - self._snapshot.captured_at).total_seconds())
            score += min(300.0, age * 30.0)
        if self._snapshot is None or score > self._snapshot.score:
            self._snapshot = BoardSnapshot(out, captured_at, score)
        return True

    def peek(
        self,
        *,
        now: datetime | None = None,
        max_age_seconds: float | None = None,
    ) -> BoardSnapshot | None:
        if (
            self._snapshot is not None
            and now is not None
            and max_age_seconds is not None
            and (now - self._snapshot.captured_at).total_seconds() > max_age_seconds
        ):
            self._snapshot = None
        return self._snapshot

    def clear(self) -> None:
        self._snapshot = None


class VirtualCameraOutput:
    """Publish the already-open physical stream for Zoom to consume.

    The capture process remains the sole owner of the PTZ device; Zoom must use
    the OBS Virtual Camera exposed here instead of opening the Logitech camera
    a second time.
    """

    def __init__(self, width: int, height: int, fps: float) -> None:
        if platform.system() != "Windows":
            raise RuntimeError("--share-with-zoom is supported only on Windows")
        try:
            import pyvirtualcam
        except ImportError as error:
            raise RuntimeError(
                "pyvirtualcam is missing; run `uv sync` on the Windows lecture PC"
            ) from error
        try:
            self._camera = pyvirtualcam.Camera(
                width=width,
                height=height,
                fps=fps,
                fmt=pyvirtualcam.PixelFormat.BGR,
            )
        except Exception as error:  # noqa: BLE001 — backend supplies platform-specific errors
            raise RuntimeError(
                "No virtual-camera backend is available. Install OBS Studio, close OBS, "
                "then start lecture-camera before Zoom."
            ) from error
        print(f"[camera] Zoom feed ready as '{self._camera.device}'", flush=True)

    def send(self, frame: np.ndarray) -> None:
        self._camera.send(frame)

    def close(self) -> None:
        self._camera.close()


@dataclass(frozen=True)
class _AnalysisJob:
    frame_seq: int
    frame: np.ndarray
    captured_at: datetime
    observed_at: float
    allow_semantic: bool


@dataclass(frozen=True)
class FrameAnalysis:
    frame_seq: int
    frame: np.ndarray
    captured_at: datetime
    observed_at: float
    target_bbox: tuple[int, int, int, int] | None
    content_bbox: tuple[int, int, int, int] | None
    people: list
    error: str | None = None


class FrameAnalysisWorker:
    """Latest-frame YOLO/LLM worker; never owns the camera or PTZ COM object."""

    def __init__(
        self,
        *,
        follow_teacher: bool,
        modality: str,
        locate_target=None,
        audience_zones: tuple[NormalizedPolygon, ...] = DEFAULT_AUDIENCE_ZONES,
    ) -> None:
        from .aiming import LLMAimDetector, TeacherTracker

        self._follow_teacher = follow_teacher
        self._modality = modality
        self._audience_zones = audience_zones
        self._teacher_tracker = TeacherTracker() if follow_teacher else None
        self._target_eyes = (
            LLMAimDetector(
                locate_target,
                "teacher" if follow_teacher else modality,
                min_confidence=0.65 if follow_teacher else 0.5,
            )
            if locate_target is not None
            else None
        )
        self._board_eyes = (
            LLMAimDetector(locate_target, "board", min_confidence=0.55)
            if follow_teacher and locate_target is not None
            else None
        )
        self._condition = threading.Condition()
        self._pending: _AnalysisJob | None = None
        self._latest: FrameAnalysis | None = None
        self._semantic_requested = self._target_eyes is not None
        self._reset_requested = False
        self._stopping = False
        self._thread = threading.Thread(
            target=self._run,
            name="lecture-camera-analysis",
            daemon=True,
        )
        self._thread.start()

    def submit(
        self,
        *,
        frame_seq: int,
        frame: np.ndarray,
        captured_at: datetime,
        observed_at: float,
        allow_semantic: bool,
    ) -> None:
        # Latest-only queue: inference is allowed to skip obsolete frames, but
        # physical capture and the Zoom virtual feed never wait for it.
        job = _AnalysisJob(
            frame_seq,
            frame.copy(),
            captured_at,
            observed_at,
            allow_semantic,
        )
        with self._condition:
            self._pending = job
            self._condition.notify()

    def poll(self, after_frame_seq: int) -> FrameAnalysis | None:
        with self._condition:
            if self._latest is None or self._latest.frame_seq <= after_frame_seq:
                return None
            return self._latest

    def request_semantic_scout(self, *, reset_tracking: bool = False) -> None:
        with self._condition:
            if self._target_eyes is not None:
                self._semantic_requested = True
            if reset_tracking:
                self._reset_requested = True
            self._condition.notify()

    def close(self) -> None:
        with self._condition:
            self._stopping = True
            self._condition.notify()
        # LLM requests have their own timeout and this is a daemon thread; do
        # not freeze shutdown or Zoom teardown waiting for an external service.
        self._thread.join(timeout=0.5)

    def _run(self) -> None:
        from .aiming import detect_people, detect_target

        while True:
            with self._condition:
                while self._pending is None and not self._stopping:
                    self._condition.wait(timeout=0.5)
                if self._stopping:
                    return
                job = self._pending
                self._pending = None
                reset = self._reset_requested
                self._reset_requested = False
                use_semantic = self._semantic_requested and job.allow_semantic
                if use_semantic:
                    self._semantic_requested = False

            if reset and self._teacher_tracker is not None:
                self._teacher_tracker.reset()

            try:
                local_content = detect_target(job.frame)
                detections = detect_people(job.frame)
                semantic_target = None
                if use_semantic:
                    scout_frame = privacy_semantic_scout(
                        job.frame, detections, self._audience_zones
                    )
                    if self._board_eyes is not None:
                        semantic_board = self._board_eyes.locate(scout_frame)
                        if semantic_board is not None:
                            local_content = semantic_board
                    if self._target_eyes is not None:
                        semantic_target = self._target_eyes.locate(scout_frame)
                        if self._teacher_tracker is not None:
                            self._teacher_tracker.seed(semantic_target)

                if self._follow_teacher:
                    target_bbox = self._teacher_tracker.select(
                        detections,
                        job.frame.shape[1],
                        job.frame.shape[0],
                        local_content,
                    )
                    if target_bbox is None:
                        target_bbox = semantic_target
                    content_bbox = local_content
                else:
                    target_bbox = semantic_target or local_content
                    content_bbox = (
                        target_bbox
                        if self._modality in {"board", "slide"}
                        else local_content
                    )

                result = FrameAnalysis(
                    job.frame_seq,
                    job.frame,
                    job.captured_at,
                    job.observed_at,
                    target_bbox,
                    content_bbox,
                    detections,
                )
            except Exception as error:  # noqa: BLE001 — fail closed on any detector failure
                result = FrameAnalysis(
                    job.frame_seq,
                    job.frame,
                    job.captured_at,
                    job.observed_at,
                    None,
                    None,
                    [],
                    error=str(error),
                )

            with self._condition:
                if self._latest is None or result.frame_seq > self._latest.frame_seq:
                    self._latest = result


class SnapshotUploadWorker:
    """Bounded retrying uploader so network latency never pauses the camera."""

    def __init__(
        self,
        send_frame,
        max_pending: int = 3,
        *,
        persist_frame=None,
        drain_pending=None,
    ) -> None:
        self._send_frame = send_frame
        self._persist_frame = persist_frame
        self._drain_pending = drain_pending
        self._queue: queue.Queue[BoardSnapshot] = queue.Queue(maxsize=max_pending)
        self._stopping = threading.Event()
        self._lock = threading.Lock()
        self._sent = 0
        self._dropped = 0
        self._thread = threading.Thread(
            target=self._run,
            name="lecture-camera-upload",
            daemon=True,
        )
        self._thread.start()

    @property
    def sent(self) -> int:
        with self._lock:
            return self._sent

    @property
    def dropped(self) -> int:
        with self._lock:
            return self._dropped

    def submit(self, snapshot: BoardSnapshot) -> bool:
        if self._stopping.is_set():
            return False
        encoded = snapshot.image_b64 or encode_jpeg_b64(snapshot.frame)
        if self._persist_frame is not None:
            try:
                self._persist_frame(encoded, snapshot.captured_at)
            except Exception as error:  # noqa: BLE001 — local disk failure, fail closed
                print(f"[camera] could not persist board frame: {error}", flush=True)
                return False
        queued = BoardSnapshot(
            snapshot.frame,
            snapshot.captured_at,
            snapshot.score,
            encoded,
        )
        try:
            self._queue.put_nowait(queued)
            return True
        except queue.Full:
            # Prefer recent board state over stale backlog after a network
            # outage. The in-flight upload is untouched; only queued work drops.
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                pass
            with self._lock:
                self._dropped += 1
            self._queue.put_nowait(queued)
            print(
                "[camera] upload backlog full — dropped oldest pending frame",
                flush=True,
            )
            return True

    def close(self, timeout: float = 5.0) -> None:
        self._stopping.set()
        self._thread.join(timeout=timeout)

    def _run(self) -> None:
        while not self._stopping.is_set() or not self._queue.empty():
            try:
                snapshot = self._queue.get(timeout=0.2)
            except queue.Empty:
                if self._drain_pending is not None:
                    try:
                        self._drain_pending()
                    except Exception:
                        pass  # durable outbox remains for the next retry
                    self._stopping.wait(1.0)
                continue
            success = False
            try:
                for attempt, delay in enumerate((0.0, 1.0, 2.0), start=1):
                    if delay and self._stopping.wait(delay):
                        break
                    try:
                        result = self._send_frame(
                            snapshot.image_b64 or encode_jpeg_b64(snapshot.frame),
                            snapshot.captured_at,
                        )
                        if not result.get("ingested"):
                            raise RuntimeError("server returned ingested=0")
                        success = True
                        with self._lock:
                            self._sent += 1
                        print(
                            f"[camera] board frame captured at "
                            f"{snapshot.captured_at.isoformat()} shipped",
                            flush=True,
                        )
                        break
                    except Exception as error:  # noqa: BLE001 — bounded retry path
                        print(
                            f"[camera] upload attempt {attempt}/3 failed: {error}",
                            flush=True,
                        )
                if not success:
                    with self._lock:
                        self._dropped += 1
                    print("[camera] board frame dropped after retries", flush=True)
            finally:
                self._queue.task_done()


def make_test_board() -> np.ndarray:
    """Synthetic whiteboard frame — lets --test-frame validate the full path
    (camera PC → gateway → vision LLM → event) without a real board."""
    img = np.full((720, 1280, 3), 245, np.uint8)
    lines = [
        ("Camera pipeline test", 90, 1.6, 3),
        ("- this text was drawn, not filmed", 170, 1.0, 2),
        ("- if you can read this in the wiki,", 230, 1.0, 2),
        ("  the board channel works end to end", 290, 1.0, 2),
    ]
    for text, y, scale, thickness in lines:
        cv2.putText(
            img,
            text,
            (60, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            scale,
            (40, 40, 60),
            thickness,
            cv2.LINE_AA,
        )
    return img


# --------------------------------------------------------------------------- #
# Hardware shell
# --------------------------------------------------------------------------- #
class PTZ:
    """Best-effort UVC pan/tilt/zoom.

    On Windows, ``cap`` is normally a winptz.DirectShowCamera — a single
    DirectShow session doing both capture AND control, so ``cap.cam`` is
    already the bound IAMCameraControl interface (see winptz.py for why: two
    separate sessions caused video glitches whenever a control command
    fired). Falls back to cv2's own CAP_PROP_PAN/TILT (some cameras genuinely
    expose pan/tilt that way) if ``cap`` has no ``.cam`` — e.g. off Windows,
    or if the unified session failed to open and camera.py fell back to
    plain cv2.VideoCapture. No-ops (digital crop only) if neither answers.
    """

    # Hardware step sizes per AimController unit step. UVC units vary wildly
    # between cameras; the controller's sign/stall learning absorbs the rest.
    PAN_STEP = 1.0
    TILT_STEP = 1.0
    ZOOM_STEP = 10.0

    def __init__(
        self, cap, device: int, *, pan_sign: int = 1, tilt_sign: int = 1
    ) -> None:
        self._cap = cap
        self._cam = getattr(cap, "cam", None)
        self._pan_sign = 1 if pan_sign >= 0 else -1
        self._tilt_sign = 1 if tilt_sign >= 0 else -1
        if self._cam is not None:
            self.supported = True
        else:
            # Plain cv2.VideoCapture (unified session unavailable, or off
            # Windows) — some cameras genuinely expose pan/tilt this way.
            self.supported = cap.get(cv2.CAP_PROP_PAN) != -1.0

    def apply(self, pan: float | None, tilt: float | None, zoom: float | None) -> None:
        if self._cam is not None:
            if pan is not None or tilt is not None:
                print(
                    "[camera] --pan/--tilt ignored: this camera only supports relative moves",
                    flush=True,
                )
            if zoom is not None:
                from .winptz import FLAGS_MANUAL, ZOOM, ZOOM_MAX, ZOOM_MIN

                self._cam.Set(
                    ZOOM, max(ZOOM_MIN, min(ZOOM_MAX, int(zoom))), FLAGS_MANUAL
                )
            return
        if pan is not None:
            self._cap.set(cv2.CAP_PROP_PAN, pan)
        if tilt is not None:
            self._cap.set(cv2.CAP_PROP_TILT, tilt)
        if zoom is not None:
            self._cap.set(cv2.CAP_PROP_ZOOM, zoom)

    def _nudge_relative(self, prop: int, cv2_prop: int, step: float) -> None:
        if step == 0:
            return
        if self._cam is not None:
            from .winptz import FLAGS_MANUAL, PULSE_SECONDS

            direction = 1 if step > 0 else -1
            self._cam.Set(prop, direction, FLAGS_MANUAL)
            time.sleep(PULSE_SECONDS)
            self._cam.Set(prop, 0, FLAGS_MANUAL)
        else:
            current = self._cap.get(cv2_prop)
            self._cap.set(cv2_prop, current + step)

    def nudge_pan(self, step: float) -> None:
        # KSPROPERTY_CAMERACONTROL_PAN_RELATIVE = 10. Keep the numeric id here
        # so a non-Windows cv2 fallback never imports Windows-only packages.
        self._nudge_relative(10, cv2.CAP_PROP_PAN, step * self._pan_sign)

    def nudge_tilt(self, step: float) -> None:
        # KSPROPERTY_CAMERACONTROL_TILT_RELATIVE = 11.
        self._nudge_relative(11, cv2.CAP_PROP_TILT, step * self._tilt_sign)

    def nudge_zoom(self, step: float) -> None:
        if self._cam is not None:
            from .winptz import FLAGS_MANUAL, ZOOM, ZOOM_MAX, ZOOM_MIN

            current, _ = self._cam.Get(ZOOM)
            self._cam.Set(
                ZOOM, max(ZOOM_MIN, min(ZOOM_MAX, current + int(step))), FLAGS_MANUAL
            )
        else:
            current = self._cap.get(cv2.CAP_PROP_ZOOM)
            self._cap.set(cv2.CAP_PROP_ZOOM, max(0.0, current + step))

    def zoom_out_full(self) -> None:
        """Widest view — used when the target is lost and we re-scout."""
        if self._cam is not None:
            from .winptz import FLAGS_MANUAL, ZOOM, ZOOM_MIN

            self._cam.Set(ZOOM, ZOOM_MIN, FLAGS_MANUAL)
        else:
            self._cap.set(cv2.CAP_PROP_ZOOM, 0.0)


def open_camera(device: int):
    """Prefer the unified DirectShow session on Windows (capture + control in
    one graph — see winptz.py). Falls back to plain cv2.VideoCapture (no PTZ
    control session at all, digital crop only) off Windows or if the unified
    path fails to open for any reason."""
    if platform.system() == "Windows":
        try:
            from .winptz import DirectShowCamera

            cam = DirectShowCamera(device)
            ok, _ = cam.read()
            if ok:
                return cam
            cam.release()
        except Exception as error:  # noqa: BLE001 — pygrabber/comtypes missing, etc.
            print(
                f"[camera] unified DirectShow capture unavailable ({error}); falling back to cv2",
                flush=True,
            )
    return _open_cv2_camera(device)


def _open_cv2_camera(device: int) -> cv2.VideoCapture:
    backend = cv2.CAP_DSHOW if platform.system() == "Windows" else cv2.CAP_ANY
    cap = cv2.VideoCapture(device, backend)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open camera device {device}")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    return cap


def probe_devices(max_index: int = 10) -> list[tuple[int, int, int, bool]]:
    """Try opening camera indices 0..max_index-1; report which actually work.

    Returns (index, width, height, ptz_supported) for each device that opens
    and yields a real frame — so `--list-devices` can tell a student which
    index is the board webcam vs. a phone-as-webcam vs. a PTZ unit, without
    guessing. Best-effort: a device busy in another process is skipped.
    """
    found: list[tuple[int, int, int, bool]] = []
    for index in range(max_index):
        try:
            cap = open_camera(index)
        except Exception:  # noqa: BLE001 — no device at this index, or busy elsewhere
            continue
        try:
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            h, w = frame.shape[:2]
            ptz = PTZ(cap, index).supported
            found.append((index, w, h, ptz))
        finally:
            cap.release()
    return found


def run_agent(
    opts: CameraOptions,
    send_frame,
    locate_target=None,
    *,
    persist_frame=None,
    drain_pending=None,
) -> int:
    """Run capture without letting inference or uploads stall the video feed.

    ``send_frame(image_b64, captured_at) -> dict`` runs in a bounded upload
    worker. The main thread alone owns DirectShow/PTZ and continuously republishes
    frames to Zoom; YOLO and semantic scouts consume latest-frame copies.
    """
    from .aiming import AimController

    follow_teacher = opts.follow_teacher or opts.modality == "desk"
    cap = open_camera(opts.device)
    flip_sign = -1 if opts.flip_180 else 1
    ptz = PTZ(
        cap,
        opts.device,
        pan_sign=opts.pan_sign * flip_sign,
        tilt_sign=opts.tilt_sign * flip_sign,
    )
    if any(value is not None for value in (opts.pan, opts.tilt, opts.zoom)):
        ptz.apply(opts.pan, opts.tilt, opts.zoom)
        print(f"[camera] PTZ applied (supported={ptz.supported})", flush=True)

    aimer = (
        # The moving target is the union of lecturer + board, not the lecturer
        # alone. A wide target prevents Zoom viewers and board snapshots from
        # losing the instructional surface while the lecturer walks.
        AimController(fill_target=0.68)
        if follow_teacher
        else (AimController() if opts.auto_aim else None)
    )
    analysis = FrameAnalysisWorker(
        follow_teacher=follow_teacher,
        modality="board" if opts.modality == "desk" else opts.modality,
        locate_target=locate_target,
        audience_zones=opts.audience_zones,
    )
    uploader = SnapshotUploadWorker(
        send_frame,
        persist_frame=persist_frame,
        drain_pending=drain_pending,
    )
    policy = PeriodicSnapshotPolicy(interval_seconds=opts.min_send_seconds)
    best_board_frame = BestBoardFrame(
        audience_zones=opts.audience_zones,
        min_person_confidence=opts.privacy_min_person_confidence,
    )

    virtual_output: VirtualCameraOutput | None = None
    frame_seq = 0
    last_analysis_seq = -1
    ignore_analysis_through_seq = -1
    last_analysis_submit_at = float("-inf")
    analysis_interval = 0.35 if follow_teacher else 0.25

    last_target_bbox = None
    last_content_bbox = None
    last_seen_at: float | None = time.monotonic() if follow_teacher else None
    zoomed_out = False
    aim_settled = False
    pan_tilt_ready_at = float("-inf")
    search_not_before = float("-inf")
    last_analysis_error: str | None = None
    last_privacy_wait_log_at = float("-inf")
    last_semantic_request_at = float("-inf")

    center_deadband_x = 0.12
    center_deadband_y = 0.18
    pan_tilt_cooldown_seconds = 0.8

    if follow_teacher and ptz.supported:
        ptz.zoom_out_full()
        zoomed_out = True
        search_not_before = time.monotonic() + 0.6
        print("[camera] teacher scout — zoomed out to the full room", flush=True)

    def invalidate_coordinates(current_seq: int) -> None:
        nonlocal ignore_analysis_through_seq, last_target_bbox, last_content_bbox
        ignore_analysis_through_seq = max(ignore_analysis_through_seq, current_seq)
        last_target_bbox = None
        last_content_bbox = None
        # A crop captured before a physical move no longer represents the
        # current view and must never satisfy the next periodic upload.
        best_board_frame.clear()

    try:
        while True:
            loop_started = time.monotonic()
            ok, frame = cap.read()
            if not ok or frame is None:
                print("[camera] frame grab failed; retrying …", flush=True)
                time.sleep(0.1)
                continue

            frame_seq += 1
            if opts.flip_180:
                frame = cv2.rotate(frame, cv2.ROTATE_180)
            captured_at = datetime.now(timezone.utc)
            now = time.monotonic()

            # This path is intentionally first and contains no inference/network.
            if opts.share_with_zoom:
                if virtual_output is None:
                    height, width = frame.shape[:2]
                    virtual_fps = max(
                        10.0, min(30.0, 1.0 / max(0.03, opts.poll_seconds))
                    )
                    virtual_output = VirtualCameraOutput(width, height, virtual_fps)
                virtual_output.send(frame)

            if opts.preview:
                shown = frame.copy()
                if last_content_bbox:
                    x, y, width, height = last_content_bbox
                    cv2.rectangle(
                        shown,
                        (x, y),
                        (x + width, y + height),
                        (255, 180, 0),
                        2,
                    )
                if last_target_bbox:
                    x, y, width, height = last_target_bbox
                    cv2.rectangle(
                        shown,
                        (x, y),
                        (x + width, y + height),
                        (0, 200, 0),
                        3,
                    )
                cv2.imshow(
                    "lecture-camera (q to quit)",
                    cv2.resize(shown, (960, 540)),
                )
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

            if now - last_analysis_submit_at >= analysis_interval:
                analysis.submit(
                    frame_seq=frame_seq,
                    frame=frame,
                    captured_at=captured_at,
                    observed_at=now,
                    allow_semantic=now >= search_not_before,
                )
                last_analysis_submit_at = now

            result = analysis.poll(last_analysis_seq)
            if result is not None:
                last_analysis_seq = result.frame_seq
                if result.error:
                    if result.error != last_analysis_error:
                        print(
                            f"[camera] analysis failed closed: {result.error}",
                            flush=True,
                        )
                        last_analysis_error = result.error
                elif result.frame_seq > ignore_analysis_through_seq:
                    last_analysis_error = None
                    last_target_bbox = result.target_bbox
                    last_content_bbox = result.content_bbox

                    # This exact analyzed frame, its detections, and timestamp stay
                    # together. No stale bbox is ever applied to a newer image.
                    best_board_frame.offer(
                        result.frame,
                        result.content_bbox,
                        result.people,
                        result.captured_at,
                    )

                    framing_target = (
                        joint_framing_bbox(
                            result.target_bbox,
                            result.content_bbox,
                            result.frame.shape[1],
                            result.frame.shape[0],
                        )
                        if follow_teacher
                        else result.target_bbox
                    )

                    if framing_target is not None:
                        last_seen_at = result.observed_at
                        zoomed_out = False

                    command = (
                        aimer.observe(
                            framing_target,
                            result.frame.shape[1],
                            result.frame.shape[0],
                        )
                        if aimer is not None
                        else None
                    )
                    motion_result_fresh = now - result.observed_at <= 1.5

                    if (
                        follow_teacher
                        and framing_target is not None
                        and ptz.supported
                        and now >= search_not_before
                        and motion_result_fresh
                    ):
                        x, y, width, height = framing_target
                        cx = (x + width / 2) / result.frame.shape[1]
                        cy = (y + height / 2) / result.frame.shape[0]
                        pulsed = False
                        if now >= pan_tilt_ready_at:
                            if abs(cx - 0.5) > center_deadband_x:
                                ptz.nudge_pan(1 if cx > 0.5 else -1)
                                pulsed = True
                            if abs(cy - 0.5) > center_deadband_y:
                                ptz.nudge_tilt(1 if cy < 0.5 else -1)
                                pulsed = True
                        if pulsed:
                            print(
                                "[camera] pan/tilt pulse toward lecturer",
                                flush=True,
                            )
                            pan_tilt_ready_at = now + pan_tilt_cooldown_seconds
                            invalidate_coordinates(frame_seq)
                            aim_settled = False
                        elif command is not None and command.zoom:
                            ptz.nudge_zoom(command.zoom * PTZ.ZOOM_STEP)
                            invalidate_coordinates(frame_seq)
                            aim_settled = False

                    if (
                        not follow_teacher
                        and command is not None
                        and command.zoom
                        and ptz.supported
                        and now >= search_not_before
                        and motion_result_fresh
                    ):
                        ptz.nudge_zoom(command.zoom * PTZ.ZOOM_STEP)
                        invalidate_coordinates(frame_seq)
                        aim_settled = False

                    if (
                        follow_teacher
                        and framing_target is None
                        and last_seen_at is not None
                        and result.observed_at - last_seen_at >= opts.lost_delay_seconds
                        and not zoomed_out
                    ):
                        print(
                            "[camera] teacher/board framing lost — zooming out and re-scouting",
                            flush=True,
                        )
                        if ptz.supported:
                            ptz.zoom_out_full()
                        zoomed_out = True
                        search_not_before = now + 0.6
                        invalidate_coordinates(frame_seq)
                        analysis.request_semantic_scout(reset_tracking=True)
                        if aimer is not None:
                            aimer.reset()
                        aim_settled = False
                    elif (
                        not follow_teacher
                        and command is not None
                        and command.lost
                        and not zoomed_out
                    ):
                        print(
                            "[camera] content target lost — zooming out and re-scouting",
                            flush=True,
                        )
                        if ptz.supported:
                            ptz.zoom_out_full()
                        zoomed_out = True
                        search_not_before = now + 0.6
                        invalidate_coordinates(frame_seq)
                        analysis.request_semantic_scout()
                        aimer.reset()
                        aim_settled = False
                    elif command is not None and command.settled and not aim_settled:
                        aim_settled = True
                        print("[camera] aim settled — target framed", flush=True)

            if (
                follow_teacher
                and zoomed_out
                and now >= search_not_before
                and now - last_semantic_request_at >= 3.0
            ):
                # Keep searching at a low cadence while the room is wide. A
                # single failed semantic request must not strand the camera.
                analysis.request_semantic_scout(reset_tracking=False)
                last_semantic_request_at = now

            if policy.due(now):
                snapshot = best_board_frame.peek(
                    now=datetime.now(timezone.utc),
                    max_age_seconds=max(15.0, opts.min_send_seconds * 1.5),
                )
                if snapshot is None:
                    if now - last_privacy_wait_log_at >= 5.0:
                        print(
                            "[camera] screenshot due, but no privacy-safe board "
                            "crop is confirmed — not uploading the room",
                            flush=True,
                        )
                        last_privacy_wait_log_at = now
                elif uploader.submit(snapshot):
                    # Cadence is based on capture scheduling, not HTTP latency.
                    policy.mark_sent(now)
                    best_board_frame.clear()

            elapsed = time.monotonic() - loop_started
            time.sleep(max(0.0, opts.poll_seconds - elapsed))
    finally:
        analysis.close()
        if virtual_output is not None:
            virtual_output.close()
        cap.release()
        if opts.preview:
            cv2.destroyAllWindows()
        uploader.close()

    if uploader.dropped:
        print(
            f"[camera] upload summary: {uploader.sent} sent, "
            f"{uploader.dropped} dropped",
            flush=True,
        )
    return uploader.sent
