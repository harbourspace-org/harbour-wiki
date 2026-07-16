# lecture-capture

**The capture layer** for Harbour.Wiki — a native recorder that turns a live
lecture into the `speech` events the system fuses.

```
mic ──▶ faster-whisper (local, offline) ──▶ POST {app}/api/ingest ──▶ Harbour.Wiki ──▶ Knottra
        transcribe each chunk               modality:"speech"          (holds the Knottra key)   fuses ▶ wiki + MCP
```

It talks **only to Harbour.Wiki**, which is the single gateway to Knottra. The
recorder never holds the Knottra API key — it carries a capture token, and the
app forwards to Knottra with its own key. (Because every write goes through the
app's one key, the session is always owned by and readable by the wiki — no
per-key tenancy mismatch.) Transcription is fully local: no audio leaves the
machine.

## Prerequisites

- Python 3.10+
- A microphone
- macOS: PortAudio (bundled in the `sounddevice` wheel; if it fails to load,
  `brew install portaudio`)
- Windows: nothing extra — all dependencies ship prebuilt wheels

## Setup

```bash
cd lecture-capture
cp .env.example .env          # set HARBOUR_WIKI_BASE_URL + CAPTURE_TOKEN

# with uv (recommended):
uv sync
# …or with pip:
python -m venv .venv && source .venv/bin/activate && pip install -e .
```

## Windows lecture-PC install (step by step)

1. **Python** — install 3.11+ from <https://python.org/downloads> and tick
   **"Add python.exe to PATH"** in the installer.
2. **Git** — install <https://git-scm.com/download/win> (defaults are fine;
   its credential manager signs you into GitHub via the browser on first clone).
3. In **PowerShell**:

   ```powershell
   pip install uv
   git clone https://github.com/harbourspace-org/lecture-capture.git
   cd lecture-capture
   copy .env.example .env      # then edit .env (notepad .env)
   uv sync                     # installs deps; first run also downloads the model
   ```

4. **Microphone permission** — Settings → Privacy & security → Microphone →
   enable *"Let desktop apps access your microphone"*.
5. **Pick the right input** (lecture rooms often have several):

   ```powershell
   uv run python -m sounddevice   # lists devices with their index
   ```

   Pass the index with `--device N` (or put `AUDIO_DEVICE=N` in `.env`).
6. **Record:**

   ```powershell
   uv run lecture-capture --class algorithms-2026 --class-title "Algorithms & Data Structures" --lecture-title "Today's topic"
   ```

   Speak; each chunk prints as it is sent. **Ctrl+C** stops and finalizes.

> Non-English lectures: set `WHISPER_MODEL=base` (multilingual, not `base.en`)
> and `WHISPER_LANGUAGE=<code>` in `.env`.

> **Token:** `CAPTURE_TOKEN` must match the value set on the Harbour.Wiki
> service. If the app leaves `/api/ingest` open (no token configured), you can
> leave it empty for local dev.

## Run (supervised — the recommended way)

```bash
uv run lecturectl start --class algorithms-2026 --lecture-title "Hashing"
uv run lecturectl status   # pid, session, last log lines
uv run lecturectl stop     # graceful stop + GUARANTEED flush/finalize
```

`lecturectl` runs the recorder as a detached, supervised process: no terminal
or agent session owns it (closing things doesn't kill the lecture), a crash
restarts it automatically into the SAME lecture, and `stop` both signals the
recorder's own flush path and sends a belt-and-braces flush through the
gateway — the lecture can't be left dangling as LIVE. State lives in
`~/.lecture-capture/` (pid, session, log).

Speech and camera events are written to
`~/.lecture-capture/outbox.sqlite3` **before** HTTP delivery. A network outage,
recorder restart, or lost response therefore cannot lose material. Retries use
a stable `client_event_id`, and Knottra deduplicates that id transactionally.
If Whisper falls more than 30 seconds behind the microphone, new audio blocks
spill to session-scoped WAV files under `~/.lecture-capture/audio-spool/`
instead of growing RAM or dropping speech. Each transcript is timestamped at
the first speech sample, not after transcription finishes, so it aligns with
the correct board image.

## Run (foreground)

```bash
# with uv:
uv run lecture-capture --class algorithms-2026

# …or, in the activated venv:
lecture-capture --class algorithms-2026 --lecture-title "Hashing"
```

Speak into the mic. Each chunk prints as it's sent:

```
[capture] recording — speak into the mic. Ctrl+C to stop & flush.
[  1] (0.94) Today we're going to talk about derivatives.
[  2] (0.91) Intuitively, the derivative measures the rate of change.
```

`Ctrl+C` stops and flushes. Then open the lecture in the wiki:
`https://harbour-wiki-production.up.railway.app/course/algorithms-2026`
(or query it from Claude via the MCP endpoint).

You announce only the **class** — Harbour.Wiki decides the lecture: it resumes
the current one (started <3h ago, not finalized — recorder crash-safe) or
creates the next number. `--new-lecture` forces a fresh one.

## Options

| Flag | Env | Default | Notes |
|---|---|---|---|
| `--class` | — | *(required)* | Course id being recorded now |
| `--class-title` | `CAPTURE_CLASS_TITLE` | = class id | Course title (first creation) |
| `--lecture-title` | — | `Lecture N` | Title for today's lecture |
| `--new-lecture` | — | off | Don't resume; start the next lecture |
| `--base-url` | `HARBOUR_WIKI_BASE_URL` | `http://127.0.0.1:3000` | Harbour.Wiki (the gateway) |
| `--token` | `CAPTURE_TOKEN` | — | Must match the app's `CAPTURE_TOKEN` |
| `--model` | `WHISPER_MODEL` | `small.en` | accuracy↑; use `tiny.en`/`base.en` on a weak PC |
| `--max-utterance` | `MAX_UTTERANCE_SECONDS` | `12` | forced cut; normally cuts at natural pauses |
| `--min-confidence` | `MIN_CONFIDENCE` | `0.35` | garbled utterances below this are not sent |
| `--context` | `CAPTURE_CONTEXT` | class+lecture title | vocabulary hint (course terms) for Whisper |
| `--language` | `WHISPER_LANGUAGE` | autodetect | e.g. `en` |
| `--device` | `AUDIO_DEVICE` | system mic | Index from `python -m sounddevice` |

## Automatic three-week schedule (Windows)

`lecture-scheduler` starts and stops the complete audio + PTZ camera pipeline
from a JSON timetable. The three fixed slots are:

| Slot | Recording time |
|---|---|
| `1` | 09:00–12:30 |
| `2` | 13:00–16:30 |
| `3` | 17:00–20:30 |

Copy [schedule.example.json](schedule.example.json) to `schedule.json` and
replace its lessons with the real timetable. `start_date` is the Monday of
week 1; a lesson can use either `week` + English/Russian `day`, or an explicit ISO
`date`:

```json
{
  "timezone": "Europe/Madrid",
  "start_date": "2026-09-07",
  "weeks": 3,
  "lessons": [
    {"week": 1, "day": "monday", "slot": 1, "course": "Algorithms"},
    {"date": "2026-09-08", "slot": 2, "course": "Databases"}
  ]
}
```

The displayed course title is copied **exactly** from `course`. Lecture titles
are automatically numbered `1`, `2`, `3`, … independently inside each course.
An optional `course_id` or `lecture` can override the generated internal id or
number. Empty timetable cells are simply omitted.

From PowerShell in the `capture` directory:

```powershell
# Check every expanded date, time, course, and lecture number first.
uv run lecture-scheduler validate --schedule .\schedule.json

# Install at Windows logon and start the scheduler now.
uv run lecture-scheduler install --schedule .\schedule.json

uv run lecture-scheduler status --schedule .\schedule.json

# Remove automation later.
uv run lecture-scheduler uninstall
```

Re-run `install` after replacing the timetable; it stops the old scheduler and
loads the new file. The scheduled task runs in the interactive Windows session
because the camera and OBS Virtual Camera require it. By default the scheduler
prevents automatic PC sleep, preloads Whisper 60 seconds early without opening
the microphone, starts recording at the slot boundary, and starts the camera
only after the audio-created Harbour Wiki session is confirmed. At the end it
stops the camera, stops audio, drains the durable outbox, and flushes/finalizes
the lecture.

State survives a scheduler or PC restart in
`~/.lecture-capture/scheduler-state.json`. Logging is in `scheduler.log`,
`recorder.log`, and `camera.log` in the same directory. If Windows logs in
during an active slot, that lesson is resumed; a slot that has already ended is
marked missed and is never recorded into the next class accidentally. A fully
powered-off computer cannot wake itself, so it must be on and the classroom
user must be logged in before the first lesson.

## Board + slide camera (optional, run alongside the audio)

`lecture-camera` watches a webcam/PTZ camera and ships board or slide text
into the SAME live lecture the audio recorder started — Knottra fuses
speech + board + slide into one record. It sends the sharpest, least-occluded
board view collected during each 10-second interval. Knottra reads only the
instructional surface and merges newly visible writing with concurrent speech.

A single camera can't reliably watch the whiteboard **and** the projector at
once, so run **one process per physical camera** — one aimed at the board,
one at the screen:

```bash
# find your camera indices first (probes 0-9, reports which open + resolution):
uv run lecture-camera --list-devices

# then run both feeds together (Ctrl+C stops both):
scripts/run-cameras.sh algorithms-2026 0 1     # board=device 0, slide=device 1
```

For the PTZ classroom setup (teacher tracking + Zoom sharing), run on Windows:

```powershell
uv run lecture-camera --class algorithms-2026 --modality board --device 0 `
  --follow-teacher --share-with-zoom --preview
```

Or run a fixed board camera manually:
`uv run lecture-camera --class algorithms-2026 --modality board --device 0`.
Validate the whole path (camera → gateway → vision LLM → event) without a
real camera: add `--test-frame`. Aim a PTZ camera interactively with
`--preview` (shows what it sees; `q` quits).

| Flag | Notes |
|---|---|
| `--modality` | `board` \| `slide`; legacy `desk` now tracks the teacher but ingests as `board` |
| `--device` | Index from `--list-devices` |
| `--auto-aim` | Aim autonomously (see below) |
| `--follow-teacher` | Track the standing lecturer in the board zone; reject the seated foreground |
| `--track` | Legacy alias for `--follow-teacher` |
| `--lost-delay` | Delay before a full unzoom and semantic re-scout (default 1.5s) |
| `--share-with-zoom` | Publish the owned physical feed as an OBS Virtual Camera (Windows) |
| `--audience-zone` | Normalized polygon always masked from uploads/scouts; repeatable (default: lower 38%) |
| `--privacy-min-confidence` | Reject a board frame when a weak person detection overlaps it (default 0.35) |
| `--pan-sign` / `--tilt-sign` | Set either to `-1` if that motor moves away from the target |
| `--pan` / `--tilt` / `--zoom` | Initial PTZ position (UVC cameras only) |
| `--send-interval` | Board capture/enqueue cadence (default 10s; `--min-send` is an alias) |
| `--test-frame` | Ship one synthetic board image and exit — no camera needed |
| `--list-devices` | Probe indices 0-9, print which open, then exit |

### Teacher tracking at the board

`--follow-teacher` starts from the widest zoom and asks `/api/aim` to identify
the standing lecturer in the teaching zone. The semantic prompt explicitly
rejects seated attendees and foreground backs. Local YOLO segmentation then tracks that
person cheaply between semantic scouts. Candidate selection also requires
board proximity, rejects large/low foreground detections, and strongly prefers
the same person over time, so a student crossing the image does not steal the
camera.

If the lecturer is absent for 1.5 seconds (configurable with `--lost-delay`),
the camera zooms fully out once, waits briefly for the motor, and performs a
new semantic scout. Motor directions are calibrated independently with
`--pan-sign` and `--tilt-sign`; `--flip-180` reverses both automatically.

PTZ movement uses the padded union of **teacher + board**, and refuses to move
when either one is unconfirmed. The teacher can therefore walk along the board
without the camera centering them so tightly that Zoom viewers lose the
writing. The image sent to Knottra is still cropped to the writing surface. Within every
10-second interval the agent retains the sharpest frame with the least teacher
occlusion. The blue preview rectangle is the board sent to Knottra; green is
the lecturer being tracked.

Capture is privacy-fail-closed: if no writing-surface bbox is confirmed, no
room image is uploaded. The lower 38% of the frame is an always-masked default
audience polygon, independent of person detection. YOLO segmentation masks
detected silhouettes; a weak overlapping detection rejects the complete frame;
and a local face detector adds another blur pass where the installed OpenCV
build supports it. Foreground attendees are also masked before semantic scout
images reach `/api/aim`. Each selected image retains its actual capture
timestamp, expires after 15 seconds, and is invalidated immediately after any
PTZ movement.

Calibrate a different desk boundary in PowerShell with normalized coordinates
(top-left is `0,0`, bottom-right is `1,1`):

```powershell
uv run lecture-camera --class algorithms-2026 --follow-teacher `
  --audience-zone "0,0.70;1,0.70;1,1;0,1"
```

Repeat `--audience-zone` for non-rectangular/disconnected seating areas, or set
`CAMERA_AUDIENCE_ZONES`; separate multiple environment polygons with `|`.

### Running alongside Zoom on Windows

Do not let Zoom and `lecture-camera` open the physical Logitech PTZ device
independently. DirectShow devices and PTZ control are not reliably multi-client.
Instead use one owner and one virtual output:

1. Install OBS Studio once; its virtual-camera driver is used by `pyvirtualcam`.
2. Close OBS. Start `lecture-camera` with `--share-with-zoom` first.
3. In Zoom, select **OBS Virtual Camera**, never the physical Logitech camera.
4. Zoom may use the same physical microphone as `lecture-capture`; the recorder
   uses the normal shared PortAudio path. In Windows microphone properties,
   disable **Allow applications to take exclusive control of this device**.

This gives Zoom the full moving camera image while the capture process retains
the only DirectShow/PTZ session and independently crops board screenshots for
Knottra. If Zoom was already using the physical camera, stop its video before
starting `lecture-camera`, then switch Zoom to the virtual camera.

The DirectShow → virtual-camera loop does not execute YOLO, LLM calls, or HTTP
requests. Latest-frame analysis and a bounded retrying upload queue run in
daemon workers, so slow inference or a temporary network outage cannot block
Zoom video or camera frame acquisition. Every selected board image is also
placed in the SQLite outbox before it can be displaced from the bounded memory
queue, and an idle worker keeps retrying the durable backlog.

### Autonomous aiming (`--auto-aim`)

With `--auto-aim` the agent frames the board/screen itself — no manual
`--pan/--tilt/--zoom` needed:

1. **Scout** — ships a small screenshot to Harbour.Wiki's `/api/aim`, where
   **Claude looks at the room** and returns the target's bounding box. This
   is what distinguishes *the whiteboard* from *the projector screen* next to
   it (`--modality board` vs `slide` decides what it looks for). Zoomed-out
   wide shots give it the whole room to choose from.
2. **Aim** — teacher tracking uses calibrated pan/tilt pulses and safe zoom;
   board/slide targeting uses zoom plus a high-resolution digital crop. Motor
   signs can be inverted explicitly because UVC cameras disagree on direction.
3. **Lock** — a free local CV check watches for drift without spending an LLM
   call on every frame. The best detected writing-surface crop is shipped on
   the 10-second cadence, so handwriting reaches the fusion model at maximum
   useful resolution. If the target is gone, the camera zooms out and
   semantically re-scouts.

The LLM key stays on the server (single-gateway rule) — the lecture PC only
sends screenshots with its capture token. If `/api/aim` is unreachable the
agent falls back to pure local CV. On a fixed webcam (no motors) `--auto-aim`
still helps: the digital crop alone ships the board region instead of the
whole room. Use `--preview` to watch it work — the detected target is
outlined in green.

Code and diagrams captured off a board/slide are kept as fenced Markdown
blocks (exact indentation, no paraphrasing) all the way into the rendered
lecture notes — not flattened into prose.

## Capture quality

The recorder is tuned for hard rooms: utterances are cut at natural pauses
(never mid-word), quiet mics are auto-normalized, Whisper runs with beam
search + a course-vocabulary hint, and its classic hallucinations (invented
text over noise, repetition loops) are dropped by per-segment quality gates.
Utterances still below `--min-confidence` are printed locally but NOT sent.

Software can't fix physics: a laptop mic 8 m from the lecturer will always be
poor. A $20 USB conference/lavalier mic near the speaker improves quality far
more than any setting here. Pick the right input with `--device`.
