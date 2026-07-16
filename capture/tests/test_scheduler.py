import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from lecture_capture.scheduler import (
    SchedulerEngine,
    StateStore,
    WindowsProcessController,
    load_schedule,
)


def write_schedule(tmp_path: Path, lessons: list[dict], **overrides) -> Path:
    body = {
        "timezone": "Europe/Madrid",
        "start_date": "2026-09-07",
        "weeks": 3,
        "prewarm_seconds": 60,
        "workdir": str(tmp_path),
        "camera": {"enabled": True, "device": 0},
        "lessons": lessons,
        **overrides,
    }
    path = tmp_path / "schedule.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def test_schedule_expands_weekdays_slots_and_numbers_per_course(tmp_path):
    path = write_schedule(
        tmp_path,
        [
            {"week": 1, "day": "monday", "slot": 1, "course": "Algorithms"},
            {"week": 1, "day": "вторник", "slot": 2, "course": "Databases"},
            {"week": 1, "day": "wednesday", "slot": 3, "course": "Algorithms"},
            {"date": "2026-09-14", "slot": 1, "course": "Algorithms"},
        ],
    )
    schedule = load_schedule(path)
    assert schedule.timezone.key == "Europe/Madrid"
    algorithms = [
        lesson for lesson in schedule.lessons if lesson.course_name == "Algorithms"
    ]
    assert [lesson.lecture_number for lesson in algorithms] == [1, 2, 3]
    assert algorithms[0].starts_at.strftime("%Y-%m-%d %H:%M") == "2026-09-07 09:00"
    assert algorithms[0].ends_at.strftime("%H:%M") == "12:30"
    assert algorithms[1].starts_at.strftime("%H:%M") == "17:00"
    assert schedule.lessons[1].course_name == "Databases"
    assert schedule.lessons[1].lecture_number == 1


def test_schedule_rejects_two_courses_in_same_slot(tmp_path):
    path = write_schedule(
        tmp_path,
        [
            {"week": 1, "day": "monday", "slot": 1, "course": "Algorithms"},
            {"date": "2026-09-07", "slot": 1, "course": "Databases"},
        ],
    )
    with pytest.raises(ValueError, match="two lessons occupy"):
        load_schedule(path)


def test_schedule_requires_week_one_to_start_on_monday(tmp_path):
    path = write_schedule(
        tmp_path,
        [{"date": "2026-09-08", "slot": 1, "course": "Algorithms"}],
        start_date="2026-09-08",
    )
    with pytest.raises(ValueError, match="Monday"):
        load_schedule(path)


def test_schedule_rejects_invalid_audience_polygon(tmp_path):
    path = write_schedule(
        tmp_path,
        [{"week": 1, "day": "monday", "slot": 1, "course": "Algorithms"}],
        camera={"audience_zones": [[[0, 0], [2, 1], [0, 1]]]},
    )
    with pytest.raises(ValueError, match="normalized"):
        load_schedule(path)


class FakeController:
    def __init__(self):
        self.audio = False
        self.camera_pid = None
        self.session_ready = False
        self.started_audio = []
        self.started_camera = []
        self.stopped_audio = 0
        self.stopped_camera = []

    def audio_running(self):
        return self.audio

    def camera_running(self, pid):
        return pid is not None and pid == self.camera_pid

    def start_audio(self, lesson):
        self.audio = True
        self.started_audio.append(lesson)
        return True

    def start_camera(self, lesson):
        if not self.session_ready:
            return None
        self.camera_pid = 4321
        self.started_camera.append(lesson)
        return self.camera_pid

    def stop_audio(self):
        self.audio = False
        self.stopped_audio += 1
        return True

    def stop_camera(self, pid):
        self.stopped_camera.append(pid)
        self.camera_pid = None
        return True


def test_engine_prewarms_then_waits_for_session_before_camera_and_stops(tmp_path):
    schedule = load_schedule(
        write_schedule(
            tmp_path,
            [{"week": 1, "day": "monday", "slot": 1, "course": "Algorithms"}],
        )
    )
    lesson = schedule.lessons[0]
    store = StateStore(tmp_path / "state.json")
    controller = FakeController()
    engine = SchedulerEngine(schedule, controller, store)

    engine.tick(lesson.starts_at - timedelta(seconds=61))
    assert not controller.started_audio
    engine.tick(lesson.starts_at - timedelta(seconds=60))
    assert controller.started_audio == [lesson]
    assert not controller.started_camera

    engine.tick(lesson.starts_at)
    assert not controller.started_camera
    controller.session_ready = True
    engine.tick(lesson.starts_at + timedelta(seconds=2))
    assert controller.started_camera == [lesson]
    assert store.read()["active"]["camera_pid"] == 4321

    engine.tick(lesson.ends_at)
    state = store.read()
    assert state["active"] is None
    assert lesson.occurrence_id in state["completed"]
    assert controller.stopped_audio == 1
    assert controller.stopped_camera == [4321]


def test_engine_marks_fully_missed_lesson_without_starting(tmp_path):
    schedule = load_schedule(
        write_schedule(
            tmp_path,
            [{"week": 1, "day": "monday", "slot": 1, "course": "Algorithms"}],
        )
    )
    controller = FakeController()
    store = StateStore(tmp_path / "state.json")
    SchedulerEngine(schedule, controller, store).tick(
        schedule.lessons[0].ends_at + timedelta(minutes=1)
    )
    assert not controller.started_audio
    assert schedule.lessons[0].occurrence_id in store.read()["missed"]
    assert SchedulerEngine(schedule, controller, store).finished()


def test_audio_command_uses_exact_names_number_and_safe_resume(tmp_path):
    schedule = load_schedule(
        write_schedule(
            tmp_path,
            [
                {
                    "week": 1,
                    "day": "monday",
                    "slot": 1,
                    "course": "Advanced Algorithms",
                }
            ],
        )
    )
    lesson = schedule.lessons[0]
    args = WindowsProcessController(schedule)._audio_args(lesson)
    assert args[args.index("--class-title") + 1] == "Advanced Algorithms"
    assert args[args.index("--lecture-title") + 1] == "1"
    assert "--new-lecture" not in args
    scheduled = datetime.fromisoformat(args[args.index("--not-before") + 1])
    assert scheduled == lesson.starts_at.astimezone(scheduled.tzinfo)
