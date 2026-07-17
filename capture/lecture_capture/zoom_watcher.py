"""zoom_watcher — start/stop audio+camera capture automatically when Zoom
launches/closes on this PC.

A lightweight trigger built on the same WindowsProcessController the 3-week
scheduler (scheduler.py) uses, for ad-hoc days that aren't on a fixed
timetable: run this once, and capture starts the moment Zoom opens and stops
(with a proper flush) the moment it closes. The course is auto-named
"Hyper.Space Class {slot}" from the SAME three daily slots the scheduler
uses (9-12:30 / 13-16:30 / 17-20:30), by whichever slot the local wall-clock
time falls in when Zoom starts — no --class needed for the normal case.

Usage:
    uv run python -m lecture_capture.zoom_watcher
    uv run python -m lecture_capture.zoom_watcher --class custom-id --class-title "Custom"
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import psutil

from . import control
from .scheduler import SLOTS, Lesson, Schedule, WindowsProcessController

POLL_SECONDS = 3.0
COURSE_BRAND = "Hyper.Space"


def zoom_running() -> bool:
    for proc in psutil.process_iter(["name"]):
        try:
            name = (proc.info["name"] or "").lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if "zoom" in name:
            return True
    return False


def start_audio_dated(schedule: Schedule, lesson: Lesson, lecture_title: str) -> bool:
    """Like WindowsProcessController.start_audio, but with an explicit
    --lecture-title (that controller hardcodes the slot number instead)."""
    args = [
        "--class", lesson.course_id,
        "--class-title", lesson.course_name,
        "--lecture-title", lecture_title,
        "--not-before", lesson.starts_at.astimezone(timezone.utc).isoformat(),
    ]
    model = schedule.audio.get("model")
    if model is not None:
        args.extend(["--model", str(model)])
    result = subprocess.run(
        [sys.executable, "-m", "lecture_capture.control", "start", *args],
        cwd=schedule.workdir,
        check=False,
    )
    return result.returncode == 0


def current_slot(now_local: datetime) -> int:
    """Which of the three daily slots `now_local`'s wall-clock time falls in.
    Outside all three (very early/late), picks the nearest by start time."""
    now_t = now_local.time()
    for slot, (start, end) in SLOTS.items():
        if start <= now_t <= end:
            return slot
    return min(SLOTS, key=lambda slot: abs(
        (now_local.replace(
            hour=SLOTS[slot][0].hour, minute=SLOTS[slot][0].minute, second=0, microsecond=0
        ) - now_local).total_seconds()
    ))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="zoom-watcher",
        description="Start audio+camera capture the moment Zoom launches; stop when it closes.",
    )
    parser.add_argument(
        "--class",
        dest="class_id",
        default=None,
        help=f"Course id (default: auto-derived as '{COURSE_BRAND.lower()}-class-N' from today's time slot)",
    )
    parser.add_argument("--class-title", default=None)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument(
        "--model",
        default="tiny.en",
        help="small.en (the lecture-capture default) contends heavily with the "
        "camera's YOLO detection for CPU on modest hardware — tiny.en avoids that.",
    )
    args = parser.parse_args(argv)

    now_local = datetime.now().astimezone()
    now = datetime.now(timezone.utc)
    slot = current_slot(now_local)
    class_id = args.class_id or f"{COURSE_BRAND.lower().replace('.', '')}-class-{slot}"
    class_title = args.class_title or f"{COURSE_BRAND} Class {slot}"
    date_str = now_local.date().isoformat()
    lesson = Lesson(
        occurrence_id="zoom-watcher",
        course_name=class_title,
        course_id=class_id,
        lecture_number=1,
        slot=slot,
        starts_at=now,
        ends_at=now + timedelta(hours=6),
    )
    schedule = Schedule(
        path=Path("zoom-watcher"),
        timezone=ZoneInfo("UTC"),
        lessons=(lesson,),
        prewarm_seconds=0.0,
        poll_seconds=POLL_SECONDS,
        prevent_sleep=False,
        workdir=Path.cwd(),
        audio={"model": args.model} if args.model else {},
        camera={
            "device": args.device,
            "modality": "board",
            # Manual zoom/aim by the operator — no autonomous PTZ movement.
            "follow_teacher": False,
            "auto_aim": False,
            "share_with_zoom": True,
            "flip_180": True,
            "preview": False,
        },
    )
    controller = WindowsProcessController(schedule)

    print("[zoom-watcher] waiting for Zoom to start …", flush=True)
    recording = False
    camera_pid: int | None = None
    try:
        while True:
            zoom_up = zoom_running()
            if zoom_up and not recording:
                print("[zoom-watcher] Zoom detected — starting capture", flush=True)
                start_audio_dated(schedule, lesson, date_str)
                # Camera resumes the audio-created session; give the gateway
                # handshake a moment to land before starting it.
                for _ in range(20):
                    time.sleep(1)
                    if control.read_state().get("session"):
                        break
                camera_pid = controller.start_camera(lesson)
                recording = True
                print("[zoom-watcher] capture running", flush=True)
            elif not zoom_up and recording:
                print("[zoom-watcher] Zoom closed — stopping capture", flush=True)
                controller.stop_camera(camera_pid)
                controller.stop_audio()
                recording = False
                camera_pid = None
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        print("\n[zoom-watcher] stopping …", flush=True)
        if recording:
            controller.stop_camera(camera_pid)
            controller.stop_audio()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
