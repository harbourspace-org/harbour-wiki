"""Windows-only: a SINGLE DirectShow session for both frame capture and PTZ
control.

Earlier this module only opened a second, separate DirectShow binding to get
IAMCameraControl (capture stayed on cv2.VideoCapture's own session). That
worked for one-off control commands, but running two independent DirectShow
sessions against the same physical device AT THE SAME TIME — one streaming
video, the other issuing pan/tilt/zoom commands — caused visible black-frame
glitches in the video whenever a command fired. Confirmed against a Logitech
PTZ Pro 2.

DirectShowCamera below replaces cv2.VideoCapture entirely on the Windows path:
one graph does capture (via a SampleGrabber, pulled synchronously through
grab_frame()) AND control (via IAMCameraControl on that same bound filter).
"""
from __future__ import annotations

import threading
from ctypes import HRESULT, POINTER, c_long

import numpy as np
from comtypes import COMMETHOD, GUID, IUnknown
from pygrabber.dshow_graph import FilterGraph

PAN_RELATIVE = 10
TILT_RELATIVE = 11
ZOOM = 3
FLAGS_MANUAL = 0x0002
PULSE_SECONDS = 0.04
ZOOM_MIN, ZOOM_MAX = 100, 1000


class IAMCameraControl(IUnknown):
    _case_insensitive_ = True
    _iid_ = GUID("{C6E13370-30AC-11d0-A18C-00A0C9118956}")
    _idlflags_: list = []


IAMCameraControl._methods_ = [
    COMMETHOD([], HRESULT, "GetRange",
              (["in"], c_long, "Property"),
              (["out"], POINTER(c_long), "pMin"),
              (["out"], POINTER(c_long), "pMax"),
              (["out"], POINTER(c_long), "pSteppingDelta"),
              (["out"], POINTER(c_long), "pDefault"),
              (["out"], POINTER(c_long), "pCapsFlags")),
    COMMETHOD([], HRESULT, "Set",
              (["in"], c_long, "Property"),
              (["in"], c_long, "lValue"),
              (["in"], c_long, "Flags")),
    COMMETHOD([], HRESULT, "Get",
              (["in"], c_long, "Property"),
              (["out"], POINTER(c_long), "lValue"),
              (["out"], POINTER(c_long), "Flags")),
]


def _relative_ptz_supported(cam: IAMCameraControl) -> bool:
    try:
        cam.GetRange(PAN_RELATIVE)
        cam.GetRange(TILT_RELATIVE)
        return True
    except Exception:  # noqa: BLE001 — any failure just means "not this way"
        return False


class DirectShowCamera:
    """cv2.VideoCapture-shaped (read()/release()) capture object, backed by
    ONE DirectShow graph that also exposes `.cam` (IAMCameraControl, or None
    if this hardware doesn't support the relative pan/tilt properties)."""

    def __init__(self, device_index: int) -> None:
        self._frame: np.ndarray | None = None
        self._frame_ready = threading.Event()
        self._lock = threading.Lock()

        self._graph = FilterGraph()
        self._graph.add_video_input_device(device_index)
        raw_cam = self._graph.get_input_device().instance.QueryInterface(IAMCameraControl)

        self._graph.add_sample_grabber(self._on_frame)
        self._graph.add_null_render()
        self._graph.prepare_preview_graph()
        self._graph.run()
        # The GetRange capability check only answers correctly once the graph
        # is actually running — checking before run() reports everything as
        # unsupported, even properties this hardware genuinely implements.
        self.cam = raw_cam if _relative_ptz_supported(raw_cam) else None

    def _on_frame(self, img: np.ndarray) -> None:
        with self._lock:
            # Confirmed empirically: pygrabber's RGB24 buffer is actually in
            # R,G,B channel order (not BGR as DIB convention would suggest) —
            # swap to match cv2's BGR convention used everywhere else in this
            # codebase (small_gray, encode_jpeg_b64, YOLO's predict, etc).
            self._frame = np.ascontiguousarray(img[:, :, ::-1])
        self._frame_ready.set()

    def read(self, timeout: float = 2.0) -> tuple[bool, np.ndarray | None]:
        self._frame_ready.clear()
        if not self._graph.grab_frame():
            return False, None
        if not self._frame_ready.wait(timeout):
            return False, None
        with self._lock:
            frame = self._frame
        return frame is not None, frame

    def release(self) -> None:
        self._graph.stop()
