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

## Run

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

## Board + slide camera (optional, run alongside the audio)

`lecture-camera` watches a webcam/PTZ camera and ships board or slide text
into the SAME live lecture the audio recorder started — Knottra fuses
speech + board + slide into one record. It only sends a frame once the view
holds still and has actually changed, so it won't spam mid-write photos.

A single camera can't reliably watch the whiteboard **and** the projector at
once, so run **one process per physical camera** — one aimed at the board,
one at the screen:

```bash
# find your camera indices first (probes 0-9, reports which open + resolution):
uv run lecture-camera --list-devices

# then run both feeds together (Ctrl+C stops both):
scripts/run-cameras.sh algorithms-2026 0 1     # board=device 0, slide=device 1
```

Or run one manually: `uv run lecture-camera --class algorithms-2026 --modality board --device 0`.
Validate the whole path (camera → gateway → vision LLM → event) without a
real camera: add `--test-frame`. Aim a PTZ camera interactively with
`--preview` (shows what it sees; `q` quits).

| Flag | Notes |
|---|---|
| `--modality` | `board` \| `slide` \| `desk` — what this camera watches |
| `--device` | Index from `--list-devices` |
| `--auto-aim` | Aim autonomously (see below) |
| `--track` | Nudge PTZ pan toward sustained motion (the teacher) |
| `--pan` / `--tilt` / `--zoom` | Initial PTZ position (UVC cameras only) |
| `--min-send` | Minimum seconds between shipped frames (default 20) |
| `--test-frame` | Ship one synthetic board image and exit — no camera needed |
| `--list-devices` | Probe indices 0-9, print which open, then exit |

### Autonomous aiming (`--auto-aim`)

With `--auto-aim` the agent frames the board/screen itself — no manual
`--pan/--tilt/--zoom` needed:

1. **Scout** — ships a small screenshot to Harbour.Wiki's `/api/aim`, where
   **Claude looks at the room** and returns the target's bounding box. This
   is what distinguishes *the whiteboard* from *the projector screen* next to
   it (`--modality board` vs `slide` decides what it looks for). Zoomed-out
   wide shots give it the whole room to choose from.
2. **Aim** — on a PTZ camera, drives pan/tilt/zoom in a closed feedback loop
   until the target is centered and fills ~60% of the frame, re-screenshotting
   and re-asking as it moves. It learns each motor's direction from how the
   target actually moves (cameras disagree on sign conventions) and freezes
   any axis that has no effect.
3. **Lock** — normal stable-and-changed shipping; a free local CV check (the
   largest bright rectangle) watches for drift every poll, so no LLM calls
   are burned while nothing changes. Every shipped frame is **digitally
   cropped to the detected target**, so handwriting arrives at the fusion
   model at maximum resolution. If the target seems gone, Claude gets one
   confirming look (glare/people can blind the CV check) before the camera
   zooms out and re-scouts.

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
