"""Three-week lecture timetable runner for the Windows classroom PC.

The scheduler is intentionally a small long-running coordinator. Windows Task
Scheduler starts it at interactive logon; it pre-warms Whisper, starts the
camera only after the audio process has opened the server-side lecture, and
flushes/stops both streams at the exact slot boundary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time as clock_time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import control
from .outbox import DurableOutbox
from .remote_control import RemoteCommand, RemoteControlClient

SLOTS: dict[int, tuple[clock_time, clock_time]] = {
    1: (clock_time(9, 0), clock_time(12, 30)),
    2: (clock_time(13, 0), clock_time(16, 30)),
    3: (clock_time(17, 0), clock_time(20, 30)),
}
WEEKDAYS = {
    "monday": 0,
    "понедельник": 0,
    "tuesday": 1,
    "вторник": 1,
    "wednesday": 2,
    "среда": 2,
    "thursday": 3,
    "четверг": 3,
    "friday": 4,
    "пятница": 4,
    "saturday": 5,
    "суббота": 5,
    "sunday": 6,
    "воскресенье": 6,
}
TASK_NAME = "HarbourWikiLectureScheduler"
SCHEDULER_STATE = control.STATE_DIR / "scheduler-state.json"
SCHEDULER_PID = control.STATE_DIR / "scheduler.pid"
SCHEDULER_LOG = control.STATE_DIR / "scheduler.log"
CAMERA_LOG = control.STATE_DIR / "camera.log"
LAUNCHER = control.STATE_DIR / "run-scheduler.cmd"


@dataclass(frozen=True)
class Lesson:
    occurrence_id: str
    course_name: str
    course_id: str
    lecture_number: int
    slot: int
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True)
class Schedule:
    path: Path
    timezone: ZoneInfo
    lessons: tuple[Lesson, ...]
    prewarm_seconds: float
    poll_seconds: float
    prevent_sleep: bool
    workdir: Path
    audio: dict
    camera: dict
    agent_id: str
    heartbeat_seconds: float


def _course_id(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = "-".join(
        "".join(c.lower() if c.isalnum() else " " for c in ascii_name).split()
    )
    return slug[:160] or "course-" + hashlib.sha256(name.encode()).hexdigest()[:12]


def _lesson_date(raw: dict, start_date: date, weeks: int) -> date:
    if raw.get("date"):
        try:
            lesson_date = date.fromisoformat(str(raw["date"]))
        except ValueError as error:
            raise ValueError(f"invalid lesson date: {raw['date']!r}") from error
    else:
        try:
            week = int(raw["week"])
            weekday = WEEKDAYS[str(raw["day"]).lower()]
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(
                "each lesson needs date, or week + English/Russian weekday"
            ) from error
        if not 1 <= week <= weeks:
            raise ValueError(f"lesson week must be within 1..{weeks}")
        lesson_date = start_date + timedelta(days=(week - 1) * 7 + weekday)
    period_end = start_date + timedelta(weeks=weeks)
    if not start_date <= lesson_date < period_end:
        raise ValueError(
            f"lesson {lesson_date} is outside the configured course period"
        )
    return lesson_date


def load_schedule(path: str | Path) -> Schedule:
    schedule_path = Path(path).resolve()
    try:
        raw = json.loads(schedule_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read schedule {schedule_path}: {error}") from error

    try:
        zone = ZoneInfo(str(raw.get("timezone", "Europe/Madrid")))
    except ZoneInfoNotFoundError as error:
        raise ValueError(f"unknown timezone: {raw.get('timezone')!r}") from error
    try:
        period_start = date.fromisoformat(str(raw["start_date"]))
    except (KeyError, ValueError) as error:
        raise ValueError("start_date must be an ISO date") from error
    if period_start.weekday() != 0:
        raise ValueError("start_date must be the Monday of week 1")
    weeks = int(raw.get("weeks", 3))
    if not 1 <= weeks <= 12:
        raise ValueError("weeks must be between 1 and 12")

    expanded: list[dict] = []
    seen_time: set[tuple[date, int]] = set()
    for item in raw.get("lessons", []):
        if item.get("enabled", True) is False:
            continue
        course_name = str(item.get("course", "")).strip()
        if not course_name:
            raise ValueError("every enabled lesson needs a course name")
        try:
            slot = int(item["slot"])
            start_clock, end_clock = SLOTS[slot]
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("lesson slot must be 1, 2, or 3") from error
        lesson_date = _lesson_date(item, period_start, weeks)
        key = lesson_date, slot
        if key in seen_time:
            raise ValueError(f"two lessons occupy {lesson_date} slot {slot}")
        seen_time.add(key)
        course_id = str(item.get("course_id") or _course_id(course_name)).strip()
        if not course_id or len(course_id) > 200:
            raise ValueError("course_id must contain 1..200 characters")
        expanded.append(
            {
                "course_name": course_name,
                "course_id": course_id,
                "slot": slot,
                "date": lesson_date,
                "starts_at": datetime.combine(lesson_date, start_clock, zone),
                "ends_at": datetime.combine(lesson_date, end_clock, zone),
                "lecture": item.get("lecture"),
            }
        )

    expanded.sort(key=lambda item: item["starts_at"])
    counters: dict[str, int] = {}
    lessons: list[Lesson] = []
    for item in expanded:
        previous = counters.get(item["course_id"], 0)
        if item["lecture"] is None:
            lecture_number = previous + 1
        else:
            lecture_number = int(item["lecture"])
            if lecture_number <= 0:
                raise ValueError("lecture numbers must be positive")
        counters[item["course_id"]] = max(previous, lecture_number)
        identity = (
            f"{item['course_id']}|{item['date'].isoformat()}|{item['slot']}|"
            f"{lecture_number}"
        )
        lessons.append(
            Lesson(
                occurrence_id=hashlib.sha256(identity.encode()).hexdigest()[:24],
                course_name=item["course_name"],
                course_id=item["course_id"],
                lecture_number=lecture_number,
                slot=item["slot"],
                starts_at=item["starts_at"],
                ends_at=item["ends_at"],
            )
        )

    if not lessons:
        raise ValueError("schedule contains no enabled lessons")
    prewarm_seconds = float(raw.get("prewarm_seconds", 60))
    poll_seconds = float(raw.get("poll_seconds", 2))
    heartbeat_seconds = float(raw.get("heartbeat_seconds", 5))
    if not 0 <= prewarm_seconds <= 1800:
        raise ValueError("prewarm_seconds must be within 0..1800")
    if not 0.25 <= poll_seconds <= 60:
        raise ValueError("poll_seconds must be within 0.25..60")
    if not 2 <= heartbeat_seconds <= 60:
        raise ValueError("heartbeat_seconds must be within 2..60")
    workdir = Path(raw.get("workdir") or schedule_path.parent).resolve()
    camera = dict(raw.get("camera") or {})
    if camera.get("modality", "board") not in {"board", "slide", "desk"}:
        raise ValueError("camera.modality must be board, slide, or desk")
    for audience_zone in camera.get("audience_zones") or []:
        if len(audience_zone) < 3:
            raise ValueError("each camera audience zone needs at least 3 points")
        for point in audience_zone:
            if (
                not isinstance(point, list | tuple)
                or len(point) != 2
                or any(not isinstance(value, int | float) for value in point)
                or any(not 0 <= float(value) <= 1 for value in point)
            ):
                raise ValueError(
                    "camera audience-zone points must be normalized [x, y]"
                )
    return Schedule(
        path=schedule_path,
        timezone=zone,
        lessons=tuple(lessons),
        prewarm_seconds=prewarm_seconds,
        poll_seconds=poll_seconds,
        prevent_sleep=bool(raw.get("prevent_sleep", True)),
        workdir=workdir,
        audio=dict(raw.get("audio") or {}),
        camera=camera,
        agent_id=str(raw.get("agent_id") or socket.gethostname()).strip(),
        heartbeat_seconds=heartbeat_seconds,
    )


class StateStore:
    def __init__(self, path: Path = SCHEDULER_STATE) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def read(self) -> dict:
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            state = {}
        return {
            "active": state.get("active"),
            "completed": list(state.get("completed") or []),
            "missed": list(state.get("missed") or []),
            "handled_commands": list(state.get("handled_commands") or []),
            "command_results": list(state.get("command_results") or []),
            "errors": list(state.get("errors") or []),
        }

    def write(self, state: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)


class WindowsProcessController:
    """Launch the existing supervised audio recorder and one camera process."""

    def __init__(self, schedule: Schedule) -> None:
        self.schedule = schedule
        control.STATE_DIR.mkdir(parents=True, exist_ok=True)

    def audio_running(self) -> bool:
        return control.read_pid() is not None

    def camera_running(self, pid: int | None) -> bool:
        if self.schedule.camera.get("enabled", True) is False:
            return True
        return pid is not None and control.pid_alive(pid)

    def zoom_status(self) -> str:
        if not self.schedule.camera.get("share_with_zoom", True):
            return "disabled"
        if os.name != "nt":
            return "unknown"
        try:  # pragma: no cover — Windows lecture PC
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq Zoom.exe", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            return "running" if '"Zoom.exe"' in result.stdout else "not-running"
        except (OSError, subprocess.SubprocessError):
            return "unknown"

    def _audio_args(self, lesson: Lesson) -> list[str]:
        args = [
            "--class",
            lesson.course_id,
            "--class-title",
            lesson.course_name,
            "--lecture-title",
            str(lesson.lecture_number),
            "--not-before",
            lesson.starts_at.astimezone(timezone.utc).isoformat(),
        ]
        mapping = {
            "device": "--device",
            "model": "--model",
            "language": "--language",
            "min_confidence": "--min-confidence",
            "max_utterance": "--max-utterance",
            "context": "--context",
        }
        for key, flag in mapping.items():
            value = self.schedule.audio.get(key)
            if value is not None:
                args.extend([flag, str(value)])
        return args

    def start_audio(self, lesson: Lesson) -> bool:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "lecture_capture.control",
                "start",
                *self._audio_args(lesson),
            ],
            cwd=self.schedule.workdir,
            check=False,
        )
        return result.returncode == 0

    def stop_audio(self) -> bool:
        result = subprocess.run(
            [sys.executable, "-m", "lecture_capture.control", "stop"],
            cwd=self.schedule.workdir,
            check=False,
        )
        return result.returncode == 0

    def _camera_args(self, lesson: Lesson) -> list[str]:
        config = self.schedule.camera
        args = [
            sys.executable,
            "-m",
            "lecture_capture.camera_cli",
            "--class",
            lesson.course_id,
            "--class-title",
            lesson.course_name,
            "--modality",
            str(config.get("modality", "board")),
            "--device",
            str(config.get("device", 0)),
        ]
        booleans = {
            "follow_teacher": "--follow-teacher",
            "share_with_zoom": "--share-with-zoom",
            "flip_180": "--flip-180",
            "preview": "--preview",
            "auto_aim": "--auto-aim",
        }
        for key, flag in booleans.items():
            if config.get(key, key in {"follow_teacher", "share_with_zoom"}):
                args.append(flag)
        values = {
            "lost_delay": "--lost-delay",
            "send_interval": "--send-interval",
            "pan_sign": "--pan-sign",
            "tilt_sign": "--tilt-sign",
            "privacy_min_confidence": "--privacy-min-confidence",
        }
        for key, flag in values.items():
            if config.get(key) is not None:
                args.extend([flag, str(config[key])])
        for zone in config.get("audience_zones") or []:
            encoded = ";".join(f"{point[0]},{point[1]}" for point in zone)
            args.extend(["--audience-zone", encoded])
        return args

    def start_camera(self, lesson: Lesson) -> int | None:
        if self.schedule.camera.get("enabled", True) is False:
            return None
        # Camera.start() resumes the audio-created live lecture. Never allow it
        # to race ahead and create a separate lecture while Whisper is warming.
        if not control.read_state().get("session"):
            return None
        kwargs: dict = {}
        if os.name == "nt":  # pragma: no cover — exercised on classroom PC
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
            )
        else:
            kwargs["start_new_session"] = True
        with open(CAMERA_LOG, "ab") as log:
            process = subprocess.Popen(
                self._camera_args(lesson),
                cwd=self.schedule.workdir,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                **kwargs,
            )
        return process.pid

    def stop_camera(self, pid: int | None) -> bool:
        if self.schedule.camera.get("enabled", True) is False:
            return True
        if pid is None or not control.pid_alive(pid):
            return True
        try:
            if os.name == "nt":  # pragma: no cover
                os.kill(pid, signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
            else:
                os.kill(pid, signal.SIGINT)
            deadline = time.monotonic() + 8
            while control.pid_alive(pid) and time.monotonic() < deadline:
                time.sleep(0.2)
            if control.pid_alive(pid):
                if os.name == "nt":  # pragma: no cover
                    subprocess.run(
                        ["taskkill", "/PID", str(pid), "/T", "/F"], check=False
                    )
                else:
                    os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return True
        return not control.pid_alive(pid)


class SchedulerEngine:
    """Pure-time coordinator; process effects are injected for unit tests."""

    def __init__(self, schedule: Schedule, controller, store: StateStore) -> None:
        self.schedule = schedule
        self.controller = controller
        self.store = store
        self.by_id = {lesson.occurrence_id: lesson for lesson in schedule.lessons}

    @staticmethod
    def _effective_end(active: dict, lesson: Lesson) -> datetime:
        override = active.get("ends_at_override")
        return datetime.fromisoformat(override) if override else lesson.ends_at

    def _finish_active(self, state: dict, lesson: Lesson) -> bool:
        active = state["active"]
        camera_ok = self.controller.stop_camera(active.get("camera_pid"))
        audio_ok = self.controller.stop_audio()
        if not (camera_ok and audio_ok):
            return False
        if lesson.occurrence_id not in state["completed"]:
            state["completed"].append(lesson.occurrence_id)
        state["active"] = None
        self.store.write(state)
        print(
            f"[scheduler] ended {lesson.course_name} lecture {lesson.lecture_number}",
            flush=True,
        )
        return True

    def tick(self, now: datetime) -> None:
        state = self.store.read()
        active = state["active"]
        if active is not None:
            lesson = self.by_id.get(active["occurrence_id"])
            if lesson is None:
                raise RuntimeError("active lesson was removed from the schedule")
            if now >= self._effective_end(active, lesson):
                self._finish_active(state, lesson)
                return
            if not self.controller.audio_running():
                if not self.controller.start_audio(lesson):
                    return
            if now >= lesson.starts_at and not self.controller.camera_running(
                active.get("camera_pid")
            ):
                camera_pid = self.controller.start_camera(lesson)
                if camera_pid is not None:
                    active["camera_pid"] = camera_pid
                    self.store.write(state)
            return

        handled = set(state["completed"]) | set(state["missed"])
        for lesson in self.schedule.lessons:
            if lesson.occurrence_id in handled:
                continue
            if now >= lesson.ends_at:
                state["missed"].append(lesson.occurrence_id)
                self.store.write(state)
                continue
            launch_at = lesson.starts_at - timedelta(
                seconds=self.schedule.prewarm_seconds
            )
            if now < launch_at:
                break
            if self.controller.audio_running():
                print(
                    "[scheduler] scheduled start blocked: another recorder is already running",
                    flush=True,
                )
                return
            if not self.controller.start_audio(lesson):
                return
            state["active"] = {
                "occurrence_id": lesson.occurrence_id,
                "camera_pid": None,
            }
            self.store.write(state)
            print(
                f"[scheduler] prepared {lesson.course_name} lecture "
                f"{lesson.lecture_number} for {lesson.starts_at.isoformat()}",
                flush=True,
            )
            if now >= lesson.starts_at:
                self.tick(now)
            return

    def apply_command(self, command: RemoteCommand, now: datetime) -> dict:
        state = self.store.read()
        if command.id in state["handled_commands"]:
            return {"id": command.id, "ok": True, "message": "already applied"}

        ok = True
        message = "done"
        try:
            if command.kind == "stop":
                active = state["active"]
                if active is None:
                    raise RuntimeError("no active lecture")
                lesson = self.by_id[active["occurrence_id"]]
                if not self._finish_active(state, lesson):
                    raise RuntimeError("capture processes did not stop cleanly")
                state = self.store.read()
                message = f"stopped {lesson.course_name} lecture {lesson.lecture_number}"
            elif command.kind == "extend":
                active = state["active"]
                if active is None:
                    raise RuntimeError("no active lecture")
                minutes = int(command.payload.get("minutes", 15))
                if not 1 <= minutes <= 180:
                    raise RuntimeError("extension must be between 1 and 180 minutes")
                lesson = self.by_id[active["occurrence_id"]]
                previous = self._effective_end(active, lesson)
                extended = previous + timedelta(minutes=minutes)
                active["ends_at_override"] = extended.isoformat()
                self.store.write(state)
                message = f"extended until {extended.isoformat()}"
            elif command.kind == "skip":
                active_id = state["active"]["occurrence_id"] if state["active"] else None
                handled = set(state["completed"]) | set(state["missed"])
                upcoming = next(
                    (
                        item
                        for item in self.schedule.lessons
                        if item.occurrence_id != active_id
                        and item.occurrence_id not in handled
                        and item.ends_at > now
                    ),
                    None,
                )
                if upcoming is None:
                    raise RuntimeError("no upcoming lecture")
                state["missed"].append(upcoming.occurrence_id)
                self.store.write(state)
                message = (
                    f"skipped {upcoming.course_name} lecture {upcoming.lecture_number}"
                )
            else:
                raise RuntimeError(f"unsupported command: {command.kind}")
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            ok = False
            message = str(error)

        state = self.store.read()
        state["handled_commands"] = (state["handled_commands"] + [command.id])[-200:]
        self.store.write(state)
        return {"id": command.id, "ok": ok, "message": message}

    def snapshot(self, now: datetime) -> dict:
        state = self.store.read()
        active_data = state["active"]
        active_lesson = (
            self.by_id.get(active_data["occurrence_id"]) if active_data else None
        )
        handled = set(state["completed"]) | set(state["missed"])
        active_id = active_lesson.occurrence_id if active_lesson else None
        upcoming = next(
            (
                item
                for item in self.schedule.lessons
                if item.occurrence_id != active_id
                and item.occurrence_id not in handled
                and item.ends_at > now
            ),
            None,
        )

        def moment(lesson: Lesson | None, end: datetime | None = None) -> dict | None:
            if lesson is None:
                return None
            return {
                "courseId": lesson.course_id,
                "courseName": lesson.course_name,
                "lecture": lesson.lecture_number,
                "slot": lesson.slot,
                "startsAt": lesson.starts_at.isoformat(),
                "endsAt": (end or lesson.ends_at).isoformat(),
            }

        camera_enabled = self.schedule.camera.get("enabled", True) is not False
        camera_running = bool(
            active_data
            and self.controller.camera_running(active_data.get("camera_pid"))
        )
        if not camera_enabled:
            camera_status = "disabled"
        elif camera_running:
            camera_status = "running"
        elif active_lesson and now < active_lesson.starts_at:
            camera_status = "prewarming"
        elif active_lesson:
            camera_status = "waiting-session"
        else:
            camera_status = "stopped"
        if active_lesson:
            scheduler_status = (
                "prewarming" if now < active_lesson.starts_at else "recording"
            )
        else:
            scheduler_status = "complete" if self.finished() else "idle"
        session_id = control.read_state().get("session") if active_lesson else None
        try:
            pending = DurableOutbox().pending_count()
        except OSError:
            pending = 0
        effective_end = (
            self._effective_end(active_data, active_lesson)
            if active_data and active_lesson
            else None
        )
        return {
            "agentId": self.schedule.agent_id,
            "hostname": socket.gethostname(),
            "schedulerStatus": scheduler_status,
            "sessionId": session_id,
            "current": moment(active_lesson, effective_end),
            "next": moment(upcoming),
            "audioStatus": "running" if self.controller.audio_running() else "stopped",
            "cameraStatus": camera_status,
            "zoomStatus": self.controller.zoom_status(),
            "outboxPending": pending,
            "errors": state["errors"][-20:],
        }

    def finished(self) -> bool:
        state = self.store.read()
        handled = set(state["completed"]) | set(state["missed"])
        return state["active"] is None and all(
            lesson.occurrence_id in handled for lesson in self.schedule.lessons
        )


def _prevent_windows_sleep(enabled: bool) -> None:
    if os.name != "nt":
        return
    import ctypes

    es_continuous = 0x80000000
    es_system_required = 0x00000001
    flags = es_continuous | es_system_required if enabled else es_continuous
    ctypes.windll.kernel32.SetThreadExecutionState(flags)  # type: ignore[attr-defined]


def _acquire_scheduler_pid() -> None:
    control.STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        existing = int(SCHEDULER_PID.read_text().strip())
    except (FileNotFoundError, ValueError):
        existing = 0
    if existing and control.pid_alive(existing):
        raise RuntimeError(f"scheduler is already running (pid {existing})")
    SCHEDULER_PID.write_text(str(os.getpid()))


def run(schedule: Schedule, *, once: bool = False) -> int:
    _acquire_scheduler_pid()
    controller = WindowsProcessController(schedule)
    engine = SchedulerEngine(schedule, controller, StateStore())
    _prevent_windows_sleep(schedule.prevent_sleep)
    try:
        while True:
            engine.tick(datetime.now(schedule.timezone))
            if once or engine.finished():
                if engine.finished():
                    print("[scheduler] timetable complete", flush=True)
                return 0
            time.sleep(schedule.poll_seconds)
    finally:
        _prevent_windows_sleep(False)
        try:
            if int(SCHEDULER_PID.read_text().strip()) == os.getpid():
                SCHEDULER_PID.unlink(missing_ok=True)
        except (FileNotFoundError, ValueError):
            pass


def _print_schedule(schedule: Schedule) -> None:
    print(f"timezone: {schedule.timezone.key}")
    for lesson in schedule.lessons:
        print(
            f"{lesson.starts_at:%Y-%m-%d %H:%M}–{lesson.ends_at:%H:%M}  "
            f"{lesson.course_name}  lecture {lesson.lecture_number}  slot {lesson.slot}"
        )


def install(schedule: Schedule, *, start_now: bool = True) -> int:
    if os.name != "nt":
        raise RuntimeError("Task Scheduler installation is supported only on Windows")
    if not schedule.workdir.is_dir():
        raise RuntimeError(f"schedule workdir does not exist: {schedule.workdir}")
    control.STATE_DIR.mkdir(parents=True, exist_ok=True)
    launcher = (
        "@echo off\r\n"
        f'cd /d "{schedule.workdir}"\r\n'
        f'"{sys.executable}" -m lecture_capture.scheduler run '
        f'--schedule "{schedule.path}" >> "{SCHEDULER_LOG}" 2>&1\r\n'
    )
    LAUNCHER.write_text(launcher, encoding="utf-8")
    # Re-installing after a timetable update must replace the currently
    # running in-memory schedule as well as the task definition.
    subprocess.run(["schtasks", "/End", "/TN", TASK_NAME], check=False)
    subprocess.run(
        [
            "schtasks",
            "/Create",
            "/TN",
            TASK_NAME,
            "/SC",
            "ONLOGON",
            "/TR",
            f'cmd.exe /d /c ""{LAUNCHER}""',
            "/F",
        ],
        check=True,
    )
    if start_now:
        subprocess.run(["schtasks", "/Run", "/TN", TASK_NAME], check=True)
    print(f"installed Windows task '{TASK_NAME}' for {schedule.path}")
    return 0


def uninstall() -> int:
    if os.name != "nt":
        raise RuntimeError("Task Scheduler installation is supported only on Windows")
    subprocess.run(["schtasks", "/End", "/TN", TASK_NAME], check=False)
    subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], check=True)
    LAUNCHER.unlink(missing_ok=True)
    print(f"removed Windows task '{TASK_NAME}'")
    return 0


def status(schedule: Schedule) -> int:
    state = StateStore().read()
    try:
        pid = int(SCHEDULER_PID.read_text().strip())
    except (FileNotFoundError, ValueError):
        pid = 0
    running = pid > 0 and control.pid_alive(pid)
    print(
        f"scheduler: {'running' if running else 'not running'}"
        + (f" (pid {pid})" if running else "")
    )
    active = state.get("active")
    if active:
        lesson = next(
            (
                item
                for item in schedule.lessons
                if item.occurrence_id == active["occurrence_id"]
            ),
            None,
        )
        if lesson:
            print(
                f"active: {lesson.course_name} lecture {lesson.lecture_number} "
                f"until {lesson.ends_at:%Y-%m-%d %H:%M}"
            )
    now = datetime.now(schedule.timezone)
    handled = set(state["completed"]) | set(state["missed"])
    upcoming = next(
        (
            lesson
            for lesson in schedule.lessons
            if lesson.occurrence_id not in handled and lesson.ends_at > now
        ),
        None,
    )
    if upcoming:
        print(
            f"next: {upcoming.starts_at:%Y-%m-%d %H:%M} "
            f"{upcoming.course_name} lecture {upcoming.lecture_number}"
        )
    print(f"completed: {len(state['completed'])}; missed: {len(state['missed'])}")
    return 0 if running else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lecture-scheduler")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "status", "run", "install"):
        child = sub.add_parser(command)
        child.add_argument("--schedule", required=True, type=Path)
        if command == "run":
            child.add_argument("--once", action="store_true")
        if command == "install":
            child.add_argument("--no-start", action="store_true")
    sub.add_parser("uninstall")
    args = parser.parse_args(argv)
    try:
        if args.command == "uninstall":
            return uninstall()
        schedule = load_schedule(args.schedule)
        if args.command == "validate":
            _print_schedule(schedule)
            return 0
        if args.command == "status":
            return status(schedule)
        if args.command == "install":
            _print_schedule(schedule)
            return install(schedule, start_now=not args.no_start)
        return run(schedule, once=args.once)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"[scheduler] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
