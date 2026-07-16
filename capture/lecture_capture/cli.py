"""Entry point: mic → local Whisper → Harbour.Wiki → Knottra, flush on exit.

The operator announces only the CLASS being recorded; the gateway decides the
lecture (resume-or-create, auto-numbered) and returns the session. Chunks are
transcribed locally and streamed as ``speech`` events; Ctrl+C stops cleanly
and flushes so the trailing window gets fused and the lecture is finalized.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import requests
from dotenv import load_dotenv

from .audio import MicStream
from .config import DEFAULT_MODEL, Config
from .gateway import Gateway
from .transcribe import Transcriber, build_context


def _build_config(argv: list[str] | None) -> Config:
    load_dotenv()
    parser = argparse.ArgumentParser(
        prog="lecture-capture",
        description="Record the class happening now and stream its notes into Harbour.Wiki.",
    )
    parser.add_argument(
        "--class",
        dest="class_id",
        required=True,
        help="Course id being recorded now (e.g. algorithms-2026)",
    )
    parser.add_argument(
        "--class-title",
        default=os.getenv("CAPTURE_CLASS_TITLE") or None,
        help="Human title for the course (used when the course is first created)",
    )
    parser.add_argument(
        "--lecture-title",
        default=None,
        help="Optional title for today's lecture (default: 'Lecture N')",
    )
    parser.add_argument(
        "--new-lecture",
        action="store_true",
        help="Force a new lecture even if a recent one could be resumed",
    )
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
        "--model",
        default=os.getenv("WHISPER_MODEL", DEFAULT_MODEL),
        help="faster-whisper model size (e.g. tiny.en, base.en, small.en)",
    )
    parser.add_argument(
        "--max-utterance",
        type=float,
        default=float(os.getenv("MAX_UTTERANCE_SECONDS", "12")),
        help="Forced cut length; normally utterances end at natural pauses",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=float(os.getenv("MIN_CONFIDENCE", "0.35")),
        help="Utterances transcribed below this confidence are not sent",
    )
    parser.add_argument(
        "--context",
        default=os.getenv("CAPTURE_CONTEXT") or None,
        help="Vocabulary hint for the transcriber (default: built from class/lecture title)",
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

    context = args.context or " ".join(
        p for p in ["University lecture.", args.class_title or args.class_id, args.lecture_title]
        if p
    )
    return Config(
        base_url=args.base_url.rstrip("/"),
        token=args.token or None,
        class_id=args.class_id,
        class_title=args.class_title,
        lecture_title=args.lecture_title,
        force_new=args.new_lecture,
        model_size=args.model,
        chunk_seconds=args.max_utterance,
        language=args.language,
        device=args.device,
        context=context,
        min_confidence=args.min_confidence,
    )


def main(argv: list[str] | None = None) -> int:
    cfg = _build_config(argv)
    gateway = Gateway(cfg)

    print(f"[capture] loading Whisper model '{cfg.model_size}' (first run downloads it) …", flush=True)
    transcriber = Transcriber(cfg.model_size, cfg.language, context=cfg.context)

    print(f"[capture] class '{cfg.class_id}' is recording — asking {cfg.base_url} …", flush=True)
    try:
        started = gateway.start()
    except requests.RequestException as error:
        print(f"[capture] could not reach Harbour.Wiki: {error}", file=sys.stderr, flush=True)
        return 1
    verb = "resuming" if started.resumed else "starting"
    print(
        f"[capture] {verb} lecture #{started.lecture} (session {started.session})",
        flush=True,
    )
    # Under lecturectl supervision: record which session we stream into, so
    # `lecturectl stop` can send a belt-and-braces flush for it.
    state_file = os.environ.get("LECTURE_STATE_FILE")
    if state_file:
        import json
        from pathlib import Path

        Path(state_file).write_text(
            json.dumps({"session": started.session, "lecture": started.lecture})
        )
    if started.vocabulary:
        transcriber.set_context(build_context(cfg.context, started.vocabulary))
        print(
            f"[capture] transcriber primed with {len(started.vocabulary)} course terms "
            f"(e.g. {', '.join(started.vocabulary[:3])})",
            flush=True,
        )

    print("[capture] recording — speak into the mic. Ctrl+C to stop & flush.", flush=True)
    events = 0
    VOCAB_REFRESH_SECONDS = 300  # today's own concepts join the bias as fusion runs
    last_vocab_refresh = time.monotonic()
    try:
        with MicStream(
            cfg.chunk_seconds,
            cfg.device,
            spool_key=started.session,
        ) as mic:
            for utterance in mic.chunks():
                if time.monotonic() - last_vocab_refresh > VOCAB_REFRESH_SECONDS:
                    last_vocab_refresh = time.monotonic()
                    try:
                        # Vocabulary only — never adopt a different session.
                        refreshed = gateway.start(adopt_session=False)
                        if refreshed.vocabulary:
                            transcriber.set_context(build_context(cfg.context, refreshed.vocabulary))
                    except requests.RequestException:
                        pass  # keep recording; retry at the next interval
                transcript = transcriber.transcribe(utterance.samples)
                if not transcript.text:
                    continue
                if transcript.confidence < cfg.min_confidence:
                    print(
                        f"[ –– ] ({transcript.confidence:.2f}) {transcript.text}  ← low confidence, not sent",
                        flush=True,
                    )
                    continue
                try:
                    gateway.send_speech(
                        transcript.text,
                        transcript.confidence,
                        utterance.started_at,
                    )
                    events += 1
                    print(f"[{events:>3}] ({transcript.confidence:.2f}) {transcript.text}", flush=True)
                except requests.RequestException as error:
                    print(f"[capture] send failed: {error}", file=sys.stderr, flush=True)
    except KeyboardInterrupt:
        print("\n[capture] stopping …", flush=True)

    try:
        gateway.flush()
        print(
            f"[capture] lecture #{started.lecture} of '{cfg.class_id}' finalized "
            f"({events} events). Fusion finishes in the background — the notes are in the wiki.",
            flush=True,
        )
    except requests.RequestException as error:
        print(f"[capture] flush failed: {error}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
