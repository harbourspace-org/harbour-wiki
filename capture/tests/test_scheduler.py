import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from lecture_capture import scheduler as scheduler_module
from lecture_capture.remote_control import RemoteCommand, ScheduleUpdate
from lecture_capture.scheduler import (
    SchedulerEngine,
    StateStore,
    WindowsProcessController,
    agent_loop,
    load_schedule,
    schedule_from_dict,
    schedule_version,
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

    def zoom_status(self):
        return "unknown"


class FakeClient:
    """Stands in for the wiki heartbeat endpoint: records every heartbeat it
    receives and hands back a pre-scripted batch of commands per call."""

    def __init__(self, command_batches):
        self.command_batches = [list(batch) for batch in command_batches]
        self.heartbeats = []  # list of (snapshot, reported_results)

    def heartbeat(self, status, command_results):
        self.heartbeats.append((status, list(command_results)))
        return self.command_batches.pop(0) if self.command_batches else []


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


def _recording_engine(tmp_path):
    """A scheduler engine that has just started its first lecture."""
    schedule = load_schedule(
        write_schedule(
            tmp_path,
            [{"week": 1, "day": "monday", "slot": 1, "course": "Algorithms"}],
        )
    )
    lesson = schedule.lessons[0]
    store = StateStore(tmp_path / "state.json")
    controller = FakeController()
    controller.session_ready = True
    engine = SchedulerEngine(schedule, controller, store)
    engine.tick(lesson.starts_at + timedelta(seconds=1))
    assert store.read()["active"] is not None
    return schedule, lesson, store, controller, engine


def test_remote_sync_publishes_snapshot_then_applies_and_reports_stop(tmp_path):
    schedule, lesson, store, controller, engine = _recording_engine(tmp_path)
    now = lesson.starts_at + timedelta(minutes=5)
    client = FakeClient([[RemoteCommand(id=7, kind="stop", payload={})], []])

    # Beat 1: snapshot (taken before the stop) shows the live lecture; the stop
    # is applied afterwards and its result is queued for the next beat.
    engine.remote_sync(client, now)
    snapshot, reported = client.heartbeats[0]
    assert reported == []
    assert snapshot["agentId"] == schedule.agent_id
    assert snapshot["current"]["courseName"] == "Algorithms"
    assert snapshot["audioStatus"] == "running"
    assert controller.stopped_audio == 1
    assert controller.stopped_camera == [4321]
    assert store.read()["active"] is None
    queued = store.read()["command_results"]
    assert queued == [{"id": 7, "ok": True, "message": queued[0]["message"]}]
    assert "stopped" in queued[0]["message"]

    # Beat 2: the stop result is reported exactly once, then cleared.
    engine.remote_sync(client, now + timedelta(seconds=5))
    _, reported = client.heartbeats[1]
    assert reported == [{"id": 7, "ok": True, "message": queued[0]["message"]}]
    assert store.read()["command_results"] == []


def test_remote_sync_extends_active_lecture(tmp_path):
    schedule, lesson, store, controller, engine = _recording_engine(tmp_path)
    now = lesson.starts_at + timedelta(minutes=5)
    client = FakeClient([[RemoteCommand(id=1, kind="extend", payload={"minutes": 20})]])

    engine.remote_sync(client, now)

    override = store.read()["active"]["ends_at_override"]
    assert datetime.fromisoformat(override) == lesson.ends_at + timedelta(minutes=20)
    assert store.read()["command_results"][0]["ok"] is True


def test_remote_sync_survives_wiki_outage_without_touching_recording(tmp_path):
    _, lesson, store, controller, engine = _recording_engine(tmp_path)

    class Boom:
        def heartbeat(self, status, command_results):
            raise RuntimeError("connection refused")

    engine.remote_sync(Boom(), lesson.starts_at + timedelta(minutes=1))

    state = store.read()
    assert state["active"] is not None  # recording untouched
    assert controller.stopped_audio == 0
    assert any("heartbeat failed" in message for message in state["errors"])


class CrashingAudioController(FakeController):
    """start_audio 'succeeds' but the recorder never stays up (audio_running
    stays False) — models a recorder that dies right after launch."""

    def start_audio(self, lesson):
        self.started_audio.append(lesson)
        return True


def test_audio_restart_is_throttled_when_recorder_keeps_dying(tmp_path):
    schedule = load_schedule(
        write_schedule(
            tmp_path,
            [{"week": 1, "day": "monday", "slot": 1, "course": "Algorithms"}],
        )
    )
    lesson = schedule.lessons[0]
    store = StateStore(tmp_path / "state.json")
    store.write(
        {
            "active": {"occurrence_id": lesson.occurrence_id, "camera_pid": None},
            "completed": [], "missed": [], "handled_commands": [],
            "command_results": [], "errors": [],
        }
    )
    controller = CrashingAudioController()
    engine = SchedulerEngine(schedule, controller, store)
    t = lesson.starts_at + timedelta(minutes=1)

    engine.tick(t)  # first attempt
    assert len(controller.started_audio) == 1
    engine.tick(t + timedelta(seconds=5))  # within cooldown -> no respawn storm
    assert len(controller.started_audio) == 1
    engine.tick(t + timedelta(seconds=40))  # past cooldown -> one more try
    assert len(controller.started_audio) == 2


def test_run_once_reports_a_single_heartbeat(tmp_path, monkeypatch):
    schedule = load_schedule(
        write_schedule(
            tmp_path,
            [{"week": 3, "day": "friday", "slot": 3, "course": "Algorithms"}],
        )
    )
    client = FakeClient([[]])
    monkeypatch.setattr(scheduler_module, "_acquire_scheduler_pid", lambda: None)
    monkeypatch.setattr(scheduler_module, "_prevent_windows_sleep", lambda enabled: None)
    monkeypatch.setattr(
        scheduler_module, "WindowsProcessController", lambda sched: FakeController()
    )
    monkeypatch.setattr(
        scheduler_module, "StateStore", lambda: StateStore(tmp_path / "run-state.json")
    )
    monkeypatch.setattr(
        scheduler_module.RemoteControlClient,
        "from_workdir",
        classmethod(lambda cls, workdir: client),
    )

    assert scheduler_module.run(schedule, once=True) == 0
    assert len(client.heartbeats) == 1
    assert client.heartbeats[0][0]["schedulerStatus"] in {"idle", "prewarming"}


# --------------------------------------------------------------------------- #
# Remote schedule agent
# --------------------------------------------------------------------------- #
def _schedule_body(**overrides) -> dict:
    body = {
        "timezone": "Europe/Madrid",
        "start_date": "2026-09-07",
        "weeks": 3,
        "camera": {"enabled": True, "device": 0},
        "lessons": [{"week": 1, "day": "monday", "slot": 1, "course": "Algorithms"}],
    }
    body.update(overrides)
    return body


class FakeScheduleClient:
    def __init__(self, updates):
        self.updates = list(updates)
        self.fetched_versions = []

    def fetch(self, current_version):
        self.fetched_versions.append(current_version)
        return self.updates.pop(0) if self.updates else None


def test_schedule_from_dict_validates_like_a_file(tmp_path):
    good = schedule_from_dict(_schedule_body(), workdir=tmp_path)
    assert good.lessons[0].course_name == "Algorithms"
    assert good.version  # a content hash was computed

    two_in_a_slot = _schedule_body(
        lessons=[
            {"week": 1, "day": "monday", "slot": 1, "course": "Algorithms"},
            {"date": "2026-09-07", "slot": 1, "course": "Databases"},
        ]
    )
    with pytest.raises(ValueError, match="two lessons occupy"):
        schedule_from_dict(two_in_a_slot, workdir=tmp_path)


def test_schedule_version_changes_with_content():
    assert schedule_version(_schedule_body()) == schedule_version(_schedule_body())
    assert schedule_version(_schedule_body()) != schedule_version(
        _schedule_body(weeks=2)
    )


def test_agent_applies_remote_schedule_and_reports_its_own_id(tmp_path):
    store = StateStore(tmp_path / "state.json")
    sched_client = FakeScheduleClient([ScheduleUpdate(body=_schedule_body(), version="v1")])
    control_client = FakeClient([[]])

    rc = agent_loop(
        "lecture-pc-3",
        tmp_path,
        iterations=1,
        schedule_client=sched_client,
        control_client=control_client,
        store=store,
        controller_factory=lambda schedule: FakeController(),
        acquire_pid=False,
    )

    assert rc == 0
    # It fetched with no version first, then reported a real heartbeat.
    assert sched_client.fetched_versions == [None]
    assert len(control_client.heartbeats) == 1
    # The CLI agent-id wins over whatever the body said.
    assert control_client.heartbeats[0][0]["agentId"] == "lecture-pc-3"


def test_agent_reports_waiting_status_before_any_schedule(tmp_path):
    store = StateStore(tmp_path / "state.json")
    sched_client = FakeScheduleClient([None])
    control_client = FakeClient([[]])

    agent_loop(
        "lecture-pc-9",
        tmp_path,
        iterations=1,
        schedule_client=sched_client,
        control_client=control_client,
        store=store,
        controller_factory=lambda schedule: FakeController(),
        acquire_pid=False,
    )

    status = control_client.heartbeats[0][0]
    assert status["agentId"] == "lecture-pc-9"
    assert status["schedulerStatus"] == "waiting-schedule"


def test_agent_survives_schedule_fetch_failure(tmp_path):
    store = StateStore(tmp_path / "state.json")

    class Boom:
        def fetch(self, current_version):
            raise RuntimeError("wiki unreachable")

    control_client = FakeClient([[]])
    agent_loop(
        "lecture-pc-1",
        tmp_path,
        iterations=1,
        schedule_client=Boom(),
        control_client=control_client,
        store=store,
        controller_factory=lambda schedule: FakeController(),
        acquire_pid=False,
    )

    assert any("schedule fetch failed" in msg for msg in store.read()["errors"])
    # Still emitted a waiting heartbeat rather than crashing.
    assert control_client.heartbeats[0][0]["schedulerStatus"] == "waiting-schedule"


def test_reconcile_drops_active_lecture_missing_from_new_schedule(tmp_path):
    schedule = schedule_from_dict(_schedule_body(), workdir=tmp_path)
    store = StateStore(tmp_path / "state.json")
    store.write(
        {
            "active": {"occurrence_id": "ghost-from-old-schedule", "camera_pid": 999},
            "completed": [],
            "missed": [],
            "handled_commands": [],
            "command_results": [],
            "errors": [],
        }
    )
    controller = FakeController()
    engine = SchedulerEngine(schedule, controller, store)

    scheduler_module._reconcile_stale_active(engine)

    assert store.read()["active"] is None
    assert controller.stopped_camera == [999]
    assert controller.stopped_audio == 1
