"""Interactive keyboard PTZ control for the PTZ Pro 2, via the confirmed-working
IAMCameraControl relative properties (KSPROPERTY_CAMERACONTROL_{PAN,TILT}_RELATIVE,
ids 10/11) and standard absolute Zoom (id 3, which we confirmed works normally).

Controls: W/S = tilt up/down, A/D = pan left/right, Z/X = zoom out/in, Q = quit.
Each key press sends ONE short pulse (with an explicit stop right after) so you
can react to what you see and stop immediately — safer than a long scripted move.
Not part of the shipped CLI — a hardware-testing tool only.
"""
import time
from ctypes import HRESULT, POINTER, c_long
from comtypes import COMMETHOD, GUID, IUnknown
import cv2
from pygrabber.dshow_graph import FilterGraph


class IAMCameraControl(IUnknown):
    _case_insensitive_ = True
    _iid_ = GUID("{C6E13370-30AC-11d0-A18C-00A0C9118956}")
    _idlflags_ = []


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

PAN_RELATIVE = 10
TILT_RELATIVE = 11
ZOOM = 3
ZOOM_MIN, ZOOM_MAX = 100, 1000  # from GetRange — Set() rejects values outside this
FLAGS_MANUAL = 0x0002
PULSE_MS = 40  # short: react to what you see rather than guessing a big move

graph = FilterGraph()
graph.add_video_input_device(0)  # PTZ Pro 2 — just bind the filter, no streaming,
cam = graph.get_input_device().instance.QueryInterface(IAMCameraControl)  # so cv2 can still open it

cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
if not cap.isOpened():
    raise RuntimeError("cv2 could not open the camera (device busy?)")

print("[ptz] W/S=tilt A/D=pan Z/X=zoom Q=quit — one short pulse per key press", flush=True)


def pulse(prop, direction):
    cam.Set(prop, direction, FLAGS_MANUAL)
    time.sleep(PULSE_MS / 1000.0)
    cam.Set(prop, 0, FLAGS_MANUAL)


try:
    while True:
        ok, frame = cap.read()
        if ok:
            cv2.imshow("PTZ keyboard control (q to quit)", cv2.resize(frame, (960, 540)))
        key = cv2.waitKey(30) & 0xFF
        if key == ord("q"):
            break
        elif key == ord("w"):
            print("[ptz] tilt +1", flush=True)
            pulse(TILT_RELATIVE, 1)
        elif key == ord("s"):
            print("[ptz] tilt -1", flush=True)
            pulse(TILT_RELATIVE, -1)
        elif key == ord("a"):
            print("[ptz] pan -1", flush=True)
            pulse(PAN_RELATIVE, -1)
        elif key == ord("d"):
            print("[ptz] pan +1", flush=True)
            pulse(PAN_RELATIVE, 1)
        elif key == ord("z"):
            print("[ptz] zoom out", flush=True)
            cam.Set(ZOOM, max(ZOOM_MIN, cam.Get(ZOOM)[0] - 10), FLAGS_MANUAL)
        elif key == ord("x"):
            print("[ptz] zoom in", flush=True)
            cam.Set(ZOOM, min(ZOOM_MAX, cam.Get(ZOOM)[0] + 10), FLAGS_MANUAL)
finally:
    cap.release()
    cv2.destroyAllWindows()
    del cam
    print("[ptz] stopped.", flush=True)
