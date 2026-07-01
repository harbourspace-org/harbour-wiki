# lecture-capture

**The missing capture layer** for Harbour.Wiki — a native recorder that turns a
live lecture into the `speech` events Knottra fuses.

```
mic ──▶ faster-whisper (local, offline) ──▶ POST /v1/sessions/{id}/events ──▶ /flush
        transcribe each chunk               modality:"speech"                 (on exit)
                                                                              └▶ Knottra fuses ▶ wiki + MCP
```

This is Layer 1–2 (capture + transcription) — deliberately **not** part of the
Knottra engine, which only ever ingests already-extracted text events. No audio
ever leaves the machine: transcription is fully local.

## Prerequisites

- Python 3.10+
- A microphone
- macOS: PortAudio (bundled in the `sounddevice` wheel; if it fails to load,
  `brew install portaudio`)

## Setup

```bash
cd capture
cp .env.example .env          # set KNOTTRA_API_KEY (see the warning in the file)

# with uv (recommended):
uv sync
# …or with pip:
python -m venv .venv && source .venv/bin/activate && pip install -e .
```

> **API key:** use the *same* key Harbour.Wiki reads with (its `KNOTTRA_API_KEY`
> on Railway). Knottra sessions are owned by the key that creates them, so a
> mismatched key makes the wiki return 403 for the lecture.

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
| `--base-url` | `KNOTTRA_BASE_URL` | `http://127.0.0.1:8000` | Deployed or local engine |
| `--api-key` | `KNOTTRA_API_KEY` | — | Same key as Harbour.Wiki |
| `--model` | `WHISPER_MODEL` | `base.en` | `tiny.en` fastest → `small.en` best |
| `--chunk-seconds` | `CHUNK_SECONDS` | `6` | Audio per event; lower = snappier, more calls |
| `--language` | `WHISPER_LANGUAGE` | autodetect | e.g. `en` |
| `--device` | `AUDIO_DEVICE` | system mic | Index from `python -m sounddevice` |
