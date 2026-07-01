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

## Setup

```bash
cd harbour-wiki/capture
cp .env.example .env          # set HARBOUR_WIKI_BASE_URL + CAPTURE_TOKEN

# with uv (recommended):
uv sync
# …or with pip:
python -m venv .venv && source .venv/bin/activate && pip install -e .
```

> **Token:** `CAPTURE_TOKEN` must match the value set on the Harbour.Wiki
> service. If the app leaves `/api/ingest` open (no token configured), you can
> leave it empty for local dev.

## Run

```bash
# with uv:
uv run lecture-capture --session cs101-lecture-3

# …or, in the activated venv:
lecture-capture --session cs101-lecture-3
```

Speak into the mic. Each chunk prints as it's sent:

```
[capture] recording — speak into the mic. Ctrl+C to stop & flush.
[  1] (0.94) Today we're going to talk about derivatives.
[  2] (0.91) Intuitively, the derivative measures the rate of change.
```

`Ctrl+C` stops and flushes. Then open the lecture in the wiki:
`https://harbour-wiki-production.up.railway.app/wiki/cs101-lecture-3`
(or query it from Claude.ai via the MCP endpoint).

## Options

| Flag | Env | Default | Notes |
|---|---|---|---|
| `--session` | — | *(required)* | Lecture / session id |
| `--base-url` | `HARBOUR_WIKI_BASE_URL` | `http://127.0.0.1:3000` | Harbour.Wiki (the gateway) |
| `--token` | `CAPTURE_TOKEN` | — | Must match the app's `CAPTURE_TOKEN` |
| `--model` | `WHISPER_MODEL` | `base.en` | `tiny.en` fastest → `small.en` best |
| `--chunk-seconds` | `CHUNK_SECONDS` | `6` | Audio per event; lower = snappier, more calls |
| `--language` | `WHISPER_LANGUAGE` | autodetect | e.g. `en` |
| `--device` | `AUDIO_DEVICE` | system mic | Index from `python -m sounddevice` |
