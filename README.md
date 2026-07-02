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
| `--model` | `WHISPER_MODEL` | `base.en` | `tiny.en` fastest → `small.en` best |
| `--chunk-seconds` | `CHUNK_SECONDS` | `6` | Audio per event; lower = snappier, more calls |
| `--language` | `WHISPER_LANGUAGE` | autodetect | e.g. `en` |
| `--device` | `AUDIO_DEVICE` | system mic | Index from `python -m sounddevice` |
