"""Camera agent: watch the lecture room, ship NEW board content as text.

The loop mirrors how a human note-taker photographs a whiteboard:
wait until the scene is STABLE (the teacher stepped away — nothing moving),
check the view actually CHANGED since the last shot, then send one frame to
Harbour.Wiki's /api/vision, where the server-side LLM transcribes it into a
``board``/``slide``/``desk`` event for the same session the audio feeds.

The when-to-shoot decision lives in :class:`SnapshotPolicy` — pure state, no
I/O — so it is unit-testable without a camera (see tests/test_camera.py).

PTZ: the Logitech PTZ Pro 2 exposes pan/tilt/zoom over UVC; on Windows OpenCV
reaches them through DirectShow properties. ``--track`` nudges the pan toward
sustained motion (the teacher) — coarse by design; a static wide shot is the
reliable default.
"""

from __future__ import annotations

import base64
import platform
import time
from dataclasses import dataclass

import cv2
import numpy as np

# Tuned for lecture rooms: calm scene for a few seconds = teacher stepped away.
STABLE_SECONDS = 3.0
MOTION_THRESHOLD = 4.0  # mean |diff| on the downsampled gray view
CHANGE_THRESHOLD = 6.0  # how different from the LAST SENT frame counts as new
SEND_MAX_WIDTH = 1280
JPEG_QUALITY = 70


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
        cv2.putText(img, text, (60, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (40, 40, 60), thickness, cv2.LINE_AA)
    return img


# --------------------------------------------------------------------------- #
# Hardware shell
# --------------------------------------------------------------------------- #
class PTZ:
    """Best-effort UVC pan/tilt/zoom via OpenCV properties. No-ops if absent."""

    def __init__(self, cap: cv2.VideoCapture) -> None:
        self._cap = cap
        # UVC PTZ properties read back -1 on cameras that lack motors.
        self.supported = cap.get(cv2.CAP_PROP_PAN) != -1.0

    def apply(self, pan: float | None, tilt: float | None, zoom: float | None) -> None:
        if pan is not None:
            self._cap.set(cv2.CAP_PROP_PAN, pan)
        if tilt is not None:
            self._cap.set(cv2.CAP_PROP_TILT, tilt)
        if zoom is not None:
            self._cap.set(cv2.CAP_PROP_ZOOM, zoom)

    def nudge_pan(self, step: float) -> None:
        current = self._cap.get(cv2.CAP_PROP_PAN)
        self._cap.set(cv2.CAP_PROP_PAN, current + step)


def open_camera(device: int) -> cv2.VideoCapture:
    # DirectShow on Windows: exposes UVC PTZ properties and avoids MSMF stalls.
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
        backend = cv2.CAP_DSHOW if platform.system() == "Windows" else cv2.CAP_ANY
        cap = cv2.VideoCapture(index, backend)
        try:
            if not cap.isOpened():
                continue
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            h, w = frame.shape[:2]
            ptz = PTZ(cap).supported
            found.append((index, w, h, ptz))
        finally:
            cap.release()
    return found


def run_agent(opts: CameraOptions, send_frame) -> int:
    """Main loop. ``send_frame(b64) -> dict`` ships one frame; returns count sent."""
    cap = open_camera(opts.device)
    ptz = PTZ(cap)
    if any(v is not None for v in (opts.pan, opts.tilt, opts.zoom)):
        ptz.apply(opts.pan, opts.tilt, opts.zoom)
        print(f"[camera] PTZ applied (supported={ptz.supported})", flush=True)

    policy = SnapshotPolicy(min_send_seconds=opts.min_send_seconds)
    prev: np.ndarray | None = None
    off_center_polls = 0
    sent = 0

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("[camera] frame grab failed; retrying …", flush=True)
                time.sleep(1)
                continue
            cur = small_gray(frame)
            now = time.monotonic()

            # --track: pan toward sustained off-center motion (the teacher).
            if opts.track and ptz.supported and prev is not None:
                cx = motion_centroid_x(prev, cur)
                if cx is not None and abs(cx - 0.5) > 0.25:
                    off_center_polls += 1
                    if off_center_polls >= 6:  # ~3s of sustained offset
                        ptz.nudge_pan(1.0 if cx > 0.5 else -1.0)
                        off_center_polls = 0
                else:
                    off_center_polls = 0

            if policy.observe(cur, now):
                try:
                    result = send_frame(encode_jpeg_b64(frame))
                    policy.mark_sent(cur, now)
                    if result.get("extracted"):
                        sent += 1
                        print(f"[{sent:>3}] {opts.modality}: {result.get('chars')} chars extracted", flush=True)
                    else:
                        print("[camera] frame had nothing readable — skipped", flush=True)
                except Exception as error:  # noqa: BLE001 — keep watching on any send failure
                    print(f"[camera] send failed: {error}", flush=True)

            if opts.preview:
                cv2.imshow("lecture-camera (q to quit)", cv2.resize(frame, (960, 540)))
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

            prev = cur
            time.sleep(opts.poll_seconds)
    finally:
        cap.release()
        if opts.preview:
            cv2.destroyAllWindows()
    return sent
