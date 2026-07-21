"""lecturectl — supervised start/stop/status for the lecture recorder.

Fixes the two failure modes real lectures hit:

- the recorder dying silently (session-bound background tasks, crashes): here
  it runs as a DETACHED process no terminal or agent session owns, and an
  in-process supervisor restarts the capture loop after a crash — resuming
  the same lecture via the gateway's resume window;
- a stop that loses the final flush (signalling the `uv` wrapper instead of
  Python): `stop` signals the supervisor Python process directly, waits for
  the clean Ctrl+C path (which flushes), and then sends a belt-and-braces
  flush through the gateway itself.

Usage:
    lecturectl start --class Linux --lecture-title "..." [any lecture-capture flags]
    lecturectl status
    lecturectl stop
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import psutil

STATE_DIR = Path.home() / ".lecture-capture"
PID_FILE = STATE_DIR / "recorder.pid"
STATE_FILE = STATE_DIR / "state.json"  # written by cli.main once the session is known
LOG_FILE = STATE_DIR / "recorder.log"

RESTART_DELAY_SECONDS = 3.0
MAX_RESTARTS = 30  # a crash every restart for 30 straight times = give up
STOP_GRACE_SECONDS = 25.0


def pid_alive(pid: int) -> bool:
    # os.kill(pid, 0) — the usual POSIX "does it exist" probe — isn't
    # supported on Windows (signal 0 raises WinError 87); psutil is
    # cross-platform and already a dependency.
    return psutil.pid_exists(pid)


def read_pid() -> int | None:
    try:
        pid = int(PID_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None
    return pid if pid_alive(pid) else None


def read_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, ValueError):
        return {}


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def cmd_start(argv: list[str]) -> int:
    if read_pid() is not None:
        state = read_state()
        print(f"recorder already running (session {state.get('session', '?')}) — `lecturectl stop` first")
        return 1
    STATE_DIR.mkdir(exist_ok=True)
    STATE_FILE.unlink(missing_ok=True)

    kwargs: dict = {}
    if os.name == "nt":  # pragma: no cover — Windows lecture PC
        # CREATE_NO_WINDOW (not DETACHED_PROCESS): a detached console app still
        # pops a console window on Windows — that spawned a storm of empty
        # PowerShell windows in the classroom. NO_WINDOW keeps the recorder
        # headless while CREATE_NEW_PROCESS_GROUP still lets `stop` deliver
        # CTRL_BREAK for a clean flush.
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        )
    else:
        kwargs["start_new_session"] = True
    with open(LOG_FILE, "ab") as log:
        child = subprocess.Popen(
            [sys.executable, "-m", "lecture_capture.control", "_supervise", *argv],
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            cwd=os.getcwd(),  # keep .env discovery working
            **kwargs,
        )
    PID_FILE.write_text(str(child.pid))
    print(f"recorder starting (pid {child.pid}), log: {LOG_FILE}")

    # Report the session once the gateway handshake lands (best-effort).
    for _ in range(30):
        time.sleep(1)
        if not pid_alive(child.pid):
            print("recorder exited during startup — last log lines:")
            _tail_log(15)
            return 1
        state = read_state()
        if state.get("session"):
            print(f"recording lecture #{state['lecture']} (session {state['session']})")
            return 0
    print("recorder is up; session not confirmed yet — check `lecturectl status`")
    return 0


def cmd_status() -> int:
    pid = read_pid()
    state = read_state()
    if pid is None:
        print("recorder: NOT RUNNING")
    else:
        print(f"recorder: running (pid {pid})")
    if state.get("session"):
        print(f"session: {state['session']} (lecture #{state.get('lecture', '?')})")
    _tail_log(5)
    return 0 if pid is not None else 1


def cmd_stop() -> int:
    pid = read_pid()
    if pid is None:
        print("recorder is not running")
    else:
        try:
            if os.name == "nt":  # pragma: no cover
                os.kill(pid, signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
            else:
                os.kill(pid, signal.SIGINT)
        except OSError as error:
            # Console-signal delivery can fail depending on how the caller
            # itself is attached to a console (WinError 87 and similar) —
            # that must not skip the belt-and-braces gateway flush below.
            print(f"graceful signal failed ({error}) — will force-terminate", flush=True)
        deadline = time.monotonic() + STOP_GRACE_SECONDS
        while pid_alive(pid) and time.monotonic() < deadline:
            time.sleep(0.5)
        if pid_alive(pid):
            print("recorder did not exit in time — terminating")
            psutil.Process(pid).terminate()
        else:
            print("recorder stopped")
    PID_FILE.unlink(missing_ok=True)

    # Belt and braces: the recorder's own Ctrl+C path flushes, but if it was
    # terminated hard (or its flush call failed) the lecture would stay open —
    # so always flush the recorded session through the gateway ourselves.
    session = read_state().get("session")
    if session:
        try:
            _gateway_flush(session)
            print(f"flush confirmed for {session}")
        except Exception as error:  # noqa: BLE001 — report, don't crash the stop
            print(f"gateway flush failed ({error}) — the lecture may still be marked LIVE")
            return 1
    return 0


def _gateway_flush(session: str) -> None:
    import requests
    from dotenv import load_dotenv

    load_dotenv()
    base = os.getenv("HARBOUR_WIKI_BASE_URL", "http://127.0.0.1:3000").rstrip("/")
    headers = {"Content-Type": "application/json"}
    token = os.getenv("CAPTURE_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = requests.post(
        f"{base}/api/ingest", json={"session": session, "flush": True}, headers=headers, timeout=30
    )
    response.raise_for_status()


def _tail_log(lines: int) -> None:
    try:
        content = LOG_FILE.read_text().splitlines()
    except FileNotFoundError:
        return
    for line in content[-lines:]:
        print(f"  {line}")


# --------------------------------------------------------------------------- #
# The detached supervisor (internal entry point)
# --------------------------------------------------------------------------- #
def _supervise(argv: list[str]) -> int:
    from . import cli

    os.environ["LECTURE_STATE_FILE"] = str(STATE_FILE)
    restarts = 0
    while True:
        try:
            code = cli.main(argv)
            print(f"[supervisor] recorder exited cleanly (code {code})", flush=True)
            break
        except KeyboardInterrupt:
            break  # cli.main handles SIGINT itself; this is a late Ctrl+C
        except Exception as error:  # noqa: BLE001 — the whole point is surviving crashes
            restarts += 1
            print(f"[supervisor] recorder crashed ({error!r}) — restart {restarts}/{MAX_RESTARTS}", flush=True)
            if restarts >= MAX_RESTARTS:
                print("[supervisor] too many crashes — giving up", flush=True)
                break
            time.sleep(RESTART_DELAY_SECONDS)
    PID_FILE.unlink(missing_ok=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else "status"
    rest = args[1:]
    if command == "start":
        return cmd_start(rest)
    if command == "stop":
        return cmd_stop()
    if command == "status":
        return cmd_status()
    if command == "_supervise":
        return _supervise(rest)
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
