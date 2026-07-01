"""Entry point: mic → local Whisper → Harbour.Wiki → Knottra, flush on exit.

Records the microphone in fixed chunks, transcribes each locally, and posts it
as a ``speech`` event to Harbour.Wiki's ingest gateway (which forwards to
Knottra). Ctrl+C stops cleanly and flushes so the trailing window gets fused.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

from .audio import MicStream
from .config import (
    DEFAULT_CHUNK_SECONDS,
    DEFAULT_DOMAIN_PROMPT,
    DEFAULT_MODEL,
    Config,
)
from .gateway import Gateway
from .transcribe import Transcriber


def _build_config(argv: list[str] | None) -> Config:
    load_dotenv()
    parser = argparse.ArgumentParser(
        prog="lecture-capture",
        description="Record a lecture and stream transcribed speech into Harbour.Wiki.",
    )
    parser.add_argument("--session", required=True, help="Session id (the lecture id)")
    parser.add_argument(
        "--base-url",
        default=os.getenv("HARBOUR_WIKI_BASE_URL", "http://127.0.0.1:3000"),
        help="Harbour.Wiki base URL (env HARBOUR_WIKI_BASE_URL)",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("CAPTURE_TOKEN", ""),
        help="Capture token for Harbour.Wiki's /api/ingest (env CAPTURE_TOKEN)",
    )
    parser.add_argument(
        "--domain-prompt",
        default=os.getenv("CAPTURE_DOMAIN_PROMPT", DEFAULT_DOMAIN_PROMPT),
        help="Fusion guidance for this session",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("WHISPER_MODEL", DEFAULT_MODEL),
        help="faster-whisper model size (e.g. tiny.en, base.en, small.en)",
    )
    parser.add_argument(
        "--chunk-seconds",
        type=float,
        default=float(os.getenv("CHUNK_SECONDS", DEFAULT_CHUNK_SECONDS)),
        help="Seconds of audio per transcription/event",
    )
    parser.add_argument(
        "--language",
        default=os.getenv("WHISPER_LANGUAGE") or None,
        help="Force a language code (e.g. en); default = autodetect",
    )
    device_env = os.getenv("AUDIO_DEVICE")
    parser.add_argument(
        "--device",
        type=int,
        default=int(device_env) if device_env else None,
        help="Input device index (see `python -m sounddevice`); default = system mic",
    )
    args = parser.parse_args(argv)

    return Config(
        base_url=args.base_url.rstrip("/"),
        token=args.token or None,
        session_id=args.session,
        domain_prompt=args.domain_prompt,
        model_size=args.model,
        chunk_seconds=args.chunk_seconds,
        language=args.language,
        device=args.device,
    )


def main(argv: list[str] | None = None) -> int:
    cfg = _build_config(argv)
    gateway = Gateway(cfg)

    print(f"[capture] loading Whisper model '{cfg.model_size}' (first run downloads it) …", flush=True)
    transcriber = Transcriber(cfg.model_size, cfg.language)

    print(f"[capture] claiming session '{cfg.session_id}' via {cfg.base_url} …", flush=True)
    try:
        gateway.ensure_session()
    except requests.RequestException as error:
        print(f"[capture] could not reach Harbour.Wiki: {error}", file=sys.stderr, flush=True)
        return 1

    print("[capture] recording — speak into the mic. Ctrl+C to stop & flush.", flush=True)
    events = 0
    try:
        with MicStream(cfg.chunk_seconds, cfg.device) as mic:
            for audio in mic.chunks():
                spoken_at = datetime.now(timezone.utc)
                transcript = transcriber.transcribe(audio)
                if not transcript.text:
                    continue
                try:
                    gateway.send_speech(transcript.text, transcript.confidence, spoken_at)
                    events += 1
                    print(f"[{events:>3}] ({transcript.confidence:.2f}) {transcript.text}", flush=True)
                except requests.RequestException as error:
                    print(f"[capture] send failed: {error}", file=sys.stderr, flush=True)
    except KeyboardInterrupt:
        print("\n[capture] stopping …", flush=True)

    try:
        gateway.flush()
        print(
            f"[capture] flushed session '{cfg.session_id}' ({events} events). "
            "Fusion runs in the background — open the wiki.",
            flush=True,
        )
    except requests.RequestException as error:
        print(f"[capture] flush failed: {error}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
