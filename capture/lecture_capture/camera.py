"""Camera agent: watch the lecture room, ship NEW board content as an image.

The loop mirrors how a human note-taker photographs a whiteboard:
wait until the scene is STABLE (the teacher stepped away — nothing moving),
check the view actually CHANGED since the last shot, then send one frame to
Harbour.Wiki's /api/vision, which forwards it AS AN IMAGE into the same
Knottra session the audio feeds — the fusion model reads the photo directly,
in the same call as whatever speech happens at that moment, rather than this
agent (or the app) pre-extracting its text.

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
    auto_aim: bool = False  # find the board/screen and frame it autonomously
    flip_180: bool = False  # camera physically mounted upside down


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

    def __init__(self, cap, device: int) -> None:
        self._cap = cap
        self._cam = getattr(cap, "cam", None)
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

                self._cam.Set(ZOOM, max(ZOOM_MIN, min(ZOOM_MAX, int(zoom))), FLAGS_MANUAL)
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
        from .winptz import PAN_RELATIVE

        self._nudge_relative(PAN_RELATIVE, cv2.CAP_PROP_PAN, step)

    def nudge_tilt(self, step: float) -> None:
        from .winptz import TILT_RELATIVE

        self._nudge_relative(TILT_RELATIVE, cv2.CAP_PROP_TILT, step)

    def nudge_zoom(self, step: float) -> None:
        if self._cam is not None:
            from .winptz import FLAGS_MANUAL, ZOOM, ZOOM_MAX, ZOOM_MIN

            current, _ = self._cam.Get(ZOOM)
            self._cam.Set(ZOOM, max(ZOOM_MIN, min(ZOOM_MAX, current + int(step))), FLAGS_MANUAL)
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
            print(f"[camera] unified DirectShow capture unavailable ({error}); falling back to cv2", flush=True)
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


def run_agent(opts: CameraOptions, send_frame, locate_target=None) -> int:
    """Main loop. ``send_frame(b64) -> dict`` ships one frame; returns count sent.

    ``locate_target(image_b64, target) -> dict`` (optional) is the server-side
    aiming brain: Claude looks at a screenshot and returns the target's bbox.
    With it, aiming decisions are LLM-driven; local CV remains the fallback
    and the cheap per-poll drift-watch once the aim has settled.
    """
    from .aiming import AimController, LLMAimDetector, crop_to_bbox, detect_person, detect_target

    is_desk = opts.modality == "desk"
    detect_fn = detect_person if is_desk else detect_target

    cap = open_camera(opts.device)
    ptz = PTZ(cap, opts.device)
    if any(v is not None for v in (opts.pan, opts.tilt, opts.zoom)):
        ptz.apply(opts.pan, opts.tilt, opts.zoom)
        print(f"[camera] PTZ applied (supported={ptz.supported})", flush=True)

    aimer = AimController() if opts.auto_aim else None
    # Desk mode tracks a MOVING person: the local YOLO detector owns aiming
    # every poll. The LLM's job is describing content downstream in Knottra,
    # not positioning — so it's never consulted here for desk.
    llm_eyes = (
        LLMAimDetector(locate_target, opts.modality)
        if (opts.auto_aim and locate_target is not None and not is_desk)
        else None
    )
    if aimer is not None:
        motors = "PTZ + digital crop" if ptz.supported else "digital crop only (no PTZ motors)"
        brain = "local YOLO person detector" if is_desk else ("Claude via /api/aim" if llm_eyes else "local CV only")
        print(f"[camera] auto-aim ON — {motors}; detection: {brain}", flush=True)
    aim_settled = False
    already_zoomed_out = False  # avoid re-sending zoom_out_full() every poll while lost
    desk_lost_episodes = 0  # consecutive "lost" firings with no reacquire — sustained-absence counter
    DESK_LOST_EPISODES_BEFORE_ZOOM_OUT = 3  # ~3 * _MAX_MISSES(8) polls of nothing, not a brief turn/occlusion
    # Desk-mode pan/tilt: bang-bang, not the AimController's incremental axis
    # logic — this hardware's pan/tilt only does large, roughly fixed-size
    # jumps regardless of pulse duration, which reads as "wrong direction" or
    # "no progress" to smooth incremental control and freezes the axis within
    # a few corrections. Instead: one pulse when clearly off-center, then wait
    # for the motor to settle and the next detection to confirm before
    # judging again. Direction convention confirmed empirically (keyboard
    # test): cx > 0.5 (right of center) -> pan +1; cy < 0.5 (above center) ->
    # tilt +1.
    DESK_CENTER_DEADBAND = 0.15
    DESK_PAN_TILT_COOLDOWN_SECONDS = 2.0
    desk_pan_tilt_ready_at = float("-inf")
    # YOLO (desk mode) costs ~200-300ms even on a modest CPU — running it every
    # poll caps the preview at a few FPS. Throttle detection; the preview still
    # redraws every loop tick regardless. detect_target (board/slide) is cheap
    # CV, no need to throttle it.
    DETECT_INTERVAL_SECONDS = 1.0
    last_detect_at = float("-inf")

    policy = SnapshotPolicy(min_send_seconds=opts.min_send_seconds)
    prev: np.ndarray | None = None
    off_center_polls = 0
    sent = 0
    last_bbox = None

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("[camera] frame grab failed; retrying …", flush=True)
                time.sleep(1)
                continue
            if opts.flip_180:
                frame = cv2.rotate(frame, cv2.ROTATE_180)
            cur = small_gray(frame)
            now = time.monotonic()

            # Repaint BEFORE the (possibly slow, ~200-300ms) detection call below —
            # cv2.waitKey() is what pumps the window's message loop on Windows, so
            # painting only at the end of the iteration left the window looking
            # blank/black for the duration of every detection call.
            if opts.preview:
                shown = frame.copy()
                if aimer is not None and last_bbox:
                    x, y, w, h = last_bbox
                    cv2.rectangle(shown, (x, y), (x + w, y + h), (0, 200, 0), 3)
                cv2.imshow("lecture-camera (q to quit)", cv2.resize(shown, (960, 540)))
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

            run_detection = not is_desk or (now - last_detect_at >= DETECT_INTERVAL_SECONDS)
            if aimer is not None and run_detection:
                last_detect_at = now
                # While converging, ask the LLM brain (it knows WHICH bright
                # rectangle is the board); once settled, watch with free local
                # CV and only call the LLM again when something seems wrong.
                if not aim_settled and llm_eyes is not None:
                    bbox = llm_eyes.locate(frame) or detect_fn(frame)
                else:
                    bbox = detect_fn(frame)
                if bbox is not None:
                    last_bbox = bbox
                    already_zoomed_out = False  # reacquired — arm the next lost-episode zoom-out
                    desk_lost_episodes = 0
                    if is_desk and ptz.supported and now >= desk_pan_tilt_ready_at:
                        x, y, w, h = bbox
                        cx = (x + w / 2) / frame.shape[1]
                        cy = (y + h / 2) / frame.shape[0]
                        pulsed = False
                        if abs(cx - 0.5) > DESK_CENTER_DEADBAND:
                            ptz.nudge_pan(-1 if cx > 0.5 else 1)
                            pulsed = True
                        if abs(cy - 0.5) > DESK_CENTER_DEADBAND:
                            ptz.nudge_tilt(-1 if cy < 0.5 else 1)
                            pulsed = True
                        if pulsed:
                            print("[camera] pan/tilt pulse toward person", flush=True)
                            desk_pan_tilt_ready_at = now + DESK_PAN_TILT_COOLDOWN_SECONDS
                command = aimer.observe(bbox, frame.shape[1], frame.shape[0])
                if command.lost:
                    # CV lost it — give Claude one look before re-scouting
                    # (glare or a person in front can blind the CV heuristic
                    # while the target is still perfectly visible).
                    confirmed = llm_eyes.locate(frame) if llm_eyes else None
                    aimer.reset()
                    if confirmed is not None:
                        last_bbox = confirmed
                        aim_settled = False  # re-converge on the confirmed spot
                        already_zoomed_out = False
                        desk_lost_episodes = 0
                    else:
                        last_bbox = None
                        # Desk mode tracks a MOVING person — briefly losing them
                        # (they turned, stepped back, got occluded) is normal and
                        # shouldn't discard hard-won zoom progress on its own. But
                        # if they've been gone for several consecutive lost
                        # episodes (not just one blip), they likely left the
                        # zoomed-in field of view entirely — zoom out so there's
                        # a chance of finding them again. Board/slide (a static
                        # target the CV heuristic genuinely lost) always re-scouts
                        # immediately.
                        if is_desk:
                            desk_lost_episodes += 1
                        should_zoom_out = not is_desk or desk_lost_episodes >= DESK_LOST_EPISODES_BEFORE_ZOOM_OUT
                        if ptz.supported and not already_zoomed_out and should_zoom_out:
                            print("[camera] target lost — zooming out to re-scout", flush=True)
                            ptz.zoom_out_full()
                            already_zoomed_out = True  # don't re-send every poll while still lost
                            desk_lost_episodes = 0
                        aim_settled = False
                elif command.moving and ptz.supported:
                    if aim_settled:
                        print("[camera] re-aiming …", flush=True)
                    aim_settled = False
                    # Pan/tilt disabled: on this hardware each pulse is a large,
                    # roughly fixed-size jump regardless of pulse duration, which
                    # the AimController's incremental sign/stall learning (tuned
                    # for smooth, proportional motors) misreads as "wrong
                    # direction" or "no progress" — freezing the axis within a
                    # few corrections. Zoom behaves smoothly and is safe to
                    # drive; digital crop (crop_to_bbox) handles the rest of the
                    # centering regardless of physical pan/tilt.
                    if command.zoom:
                        ptz.nudge_zoom(command.zoom * PTZ.ZOOM_STEP)
                    # Let the motors move before judging the result or shipping.
                    prev = cur
                    time.sleep(max(opts.poll_seconds, 0.4))
                    continue
                elif command.settled and not aim_settled:
                    aim_settled = True
                    print("[camera] aim settled — target framed", flush=True)

            # --track: pan toward sustained off-center motion (the teacher).
            # Skipped under auto-aim (the aimer owns the motors).
            if opts.track and aimer is None and ptz.supported and prev is not None:
                cx = motion_centroid_x(prev, cur)
                if cx is not None and abs(cx - 0.5) > 0.25:
                    off_center_polls += 1
                    if off_center_polls >= 6:  # ~3s of sustained offset
                        ptz.nudge_pan(1.0 if cx > 0.5 else -1.0)
                        off_center_polls = 0
                else:
                    off_center_polls = 0

            if policy.observe(cur, now):
                # Digital framing: ship the detected target region, not the
                # whole room — this is what makes handwriting legible.
                out = crop_to_bbox(frame, last_bbox) if (aimer is not None and last_bbox) else frame
                try:
                    result = send_frame(encode_jpeg_b64(out))
                    policy.mark_sent(cur, now)
                    if result.get("ingested"):
                        sent += 1
                        print(f"[{sent:>3}] {opts.modality} frame shipped", flush=True)
                    else:
                        print("[camera] frame not ingested — skipped", flush=True)
                except Exception as error:  # noqa: BLE001 — keep watching on any send failure
                    print(f"[camera] send failed: {error}", flush=True)

            prev = cur
            time.sleep(opts.poll_seconds)
    finally:
        cap.release()
        if opts.preview:
            cv2.destroyAllWindows()
    return sent
