"""start_lecture — one-shot manual start: run this once at the start of
class, and it immediately starts both audio (supervised) and camera capture
together, auto-naming the course "Hyper.Space Class {1,2,3}" from whichever
of the three daily slots (9-12:30 / 13-16:30 / 17-20:30) the current time
falls in, with today's date as the lecture title. Unlike zoom_watcher.py,
this does NOT wait for or watch Zoom — it starts capture right away.

Usage:
    uv run python -m lecture_capture.start_lecture
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import control
from .scheduler import Lesson, Schedule, WindowsProcessController
from .zoom_watcher import COURSE_BRAND, current_slot, start_audio_dated

CAMERA_PID_FILE = control.STATE_DIR / "camera.pid"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="start-lecture",
        description="Start audio+camera capture together, right now.",
    )
    parser.add_argument("--class", dest="class_id", default=None)
    parser.add_argument("--class-title", default=None)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--model", default="tiny.en")
    args = parser.parse_args(argv)

    now_local = datetime.now().astimezone()
    now = datetime.now(timezone.utc)
    slot = current_slot(now_local)
    class_id = args.class_id or f"{COURSE_BRAND.lower().replace('.', '')}-class-{slot}"
    class_title = args.class_title or f"{COURSE_BRAND} Class {slot}"
    date_str = now_local.date().isoformat()
    lesson = Lesson(
        occurrence_id="start-lecture",
        course_name=class_title,
        course_id=class_id,
        lecture_number=1,
        slot=slot,
        starts_at=now,
        ends_at=now + timedelta(hours=6),
    )
    schedule = Schedule(
        path=Path("start-lecture"),
        timezone=ZoneInfo("UTC"),
        lessons=(lesson,),
        prewarm_seconds=0.0,
        poll_seconds=3.0,
        prevent_sleep=False,
        workdir=Path.cwd(),
        audio={"model": args.model},
        camera={
            "device": args.device,
            "modality": "board",
            "follow_teacher": False,
            "auto_aim": False,
            "share_with_zoom": True,
            "flip_180": True,
            "preview": False,
        },
    )
    controller = WindowsProcessController(schedule)

    print(f"[start-lecture] starting '{class_title}' — {date_str} …", flush=True)
    start_audio_dated(schedule, lesson, date_str)
    for _ in range(20):
        time.sleep(1)
        if control.read_state().get("session"):
            break
    camera_pid = controller.start_camera(lesson)
    if camera_pid is not None:
        CAMERA_PID_FILE.write_text(str(camera_pid))
    print(
        f"[start-lecture] recording — audio + camera (pid {camera_pid}) running.\n"
        f"[start-lecture] to stop: uv run python -m lecture_capture.stop_lecture",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
