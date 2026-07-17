"""stop_lecture — companion to start_lecture.py: stops both the supervised
audio recorder (with its guaranteed gateway flush) and the camera process
started alongside it.

Usage:
    uv run python -m lecture_capture.stop_lecture
"""
from __future__ import annotations

import os
import signal
import time

import psutil

from . import control
from .start_lecture import CAMERA_PID_FILE


def stop_camera() -> None:
    try:
        pid = int(CAMERA_PID_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        print("[stop-lecture] no camera pid on record", flush=True)
        return
    if not psutil.pid_exists(pid):
        print("[stop-lecture] camera already stopped", flush=True)
        CAMERA_PID_FILE.unlink(missing_ok=True)
        return
    try:
        os.kill(pid, signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
    except OSError:
        pass
    deadline = time.monotonic() + 8
    while psutil.pid_exists(pid) and time.monotonic() < deadline:
        time.sleep(0.3)
    if psutil.pid_exists(pid):
        psutil.Process(pid).terminate()
    print("[stop-lecture] camera stopped", flush=True)
    CAMERA_PID_FILE.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    stop_camera()
    print("[stop-lecture] stopping audio (with gateway flush) …", flush=True)
    return control.main(["stop"])


if __name__ == "__main__":
    raise SystemExit(main())
