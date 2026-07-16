"""Entry point for the camera agent: PTZ camera → new board content → text events.

Run it ALONGSIDE the audio recorder for the same class: its start call resumes
the same live lecture, so speech and board fuse into one record.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

from .camera import DEFAULT_AUDIENCE_ZONES, CameraOptions, NormalizedPolygon, run_agent
from .config import Config, DEFAULT_CHUNK_SECONDS
from .gateway import Gateway


def _parse_zone(value: str) -> NormalizedPolygon:
    try:
        points = tuple(
            (float(pair.split(",", 1)[0]), float(pair.split(",", 1)[1]))
            for pair in value.split(";")
        )
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError(
            "zone must look like 0,0.62;1,0.62;1,1;0,1"
        ) from error
    if len(points) < 3 or any(not (0 <= x <= 1 and 0 <= y <= 1) for x, y in points):
        raise argparse.ArgumentTypeError("zone needs >=3 normalized points in 0..1")
    return points


def _build(
    argv: list[str] | None,
) -> tuple[Config, CameraOptions, bool, bool]:
    load_dotenv()
    parser = argparse.ArgumentParser(
        prog="lecture-camera",
        description="Watch the lecture room with a (PTZ) camera and stream board/slide text into Harbour.Wiki.",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="Probe camera indices 0-9, print which open (with resolution/PTZ), and exit",
    )
    parser.add_argument(
        "--class", dest="class_id", required=False, help="Course id being recorded now"
    )
    parser.add_argument(
        "--class-title", default=os.getenv("CAPTURE_CLASS_TITLE") or None
    )
    parser.add_argument(
        "--lecture-title", default=None, help="Used only if this starts the lecture"
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("HARBOUR_WIKI_BASE_URL", "http://127.0.0.1:3000"),
        help="Harbour.Wiki base URL (env HARBOUR_WIKI_BASE_URL)",
    )
    parser.add_argument("--token", default=os.getenv("CAPTURE_TOKEN", ""))
    parser.add_argument(
        "--modality",
        choices=["board", "slide", "desk"],
        default="board",
        help="What the camera is pointed at (default: board)",
    )
    parser.add_argument(
        "--device", type=int, default=int(os.getenv("CAMERA_DEVICE", "0"))
    )
    parser.add_argument("--pan", type=float, default=None, help="Initial PTZ pan")
    parser.add_argument("--tilt", type=float, default=None, help="Initial PTZ tilt")
    parser.add_argument("--zoom", type=float, default=None, help="Initial PTZ zoom")
    parser.add_argument(
        "--auto-aim",
        action="store_true",
        help="Find the board/screen and frame it autonomously (PTZ if available; "
        "digital crop always). Re-scouts if the target is lost.",
    )
    parser.add_argument(
        "--track",
        action="store_true",
        help="Legacy alias for --follow-teacher (motion-only audience tracking was removed)",
    )
    parser.add_argument(
        "--follow-teacher",
        action="store_true",
        help="Track only the standing lecturer in the board zone; ignore seated foreground students",
    )
    parser.add_argument(
        "--follow-local",
        action="store_true",
        help="Local-only tracking: pan/tilt/zoom toward whoever YOLO detects, no server call, "
        "no board anchor, no audience-safety filtering. For single-person/office/demo use, "
        "not classroom lectures — use --follow-teacher there.",
    )
    parser.add_argument(
        "--lost-delay",
        type=float,
        default=float(os.getenv("CAMERA_LOST_DELAY_SECONDS", "1.5")),
        help="Seconds the lecturer may be absent before zooming fully out to re-scout (default: 1.5)",
    )
    parser.add_argument(
        "--share-with-zoom",
        action="store_true",
        help="Publish this single physical capture as an OBS Virtual Camera for Zoom (Windows only)",
    )
    parser.add_argument(
        "--audience-zone",
        action="append",
        type=_parse_zone,
        default=None,
        metavar="X,Y;X,Y;...",
        help="Normalized polygon that is always masked (repeatable). Default: lower 38%% of frame",
    )
    parser.add_argument(
        "--privacy-min-confidence",
        type=float,
        default=float(os.getenv("CAMERA_PRIVACY_MIN_CONFIDENCE", "0.35")),
        help="Fail closed when a weaker person detection overlaps the board (default: 0.35)",
    )
    parser.add_argument(
        "--pan-sign",
        type=int,
        choices=[-1, 1],
        default=int(os.getenv("CAMERA_PAN_SIGN", "1")),
        help="Invert with -1 if the PTZ pans away from the lecturer",
    )
    parser.add_argument(
        "--tilt-sign",
        type=int,
        choices=[-1, 1],
        default=int(os.getenv("CAMERA_TILT_SIGN", "1")),
        help="Invert with -1 if the PTZ tilts away from the lecturer",
    )
    parser.add_argument(
        "--flip-180",
        action="store_true",
        help="Camera is physically mounted upside down — rotate every frame 180 to compensate",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Show a live window (useful for aiming; q quits)",
    )
    parser.add_argument(
        "--poll",
        type=float,
        default=0.05,
        help="Seconds between frame checks (default: 0.05)",
    )
    parser.add_argument(
        "--send-interval",
        "--min-send",
        dest="send_interval",
        type=float,
        default=float(os.getenv("CAMERA_SEND_INTERVAL_SECONDS", "10")),
        help="Ship the best board frame this often; --min-send is a legacy alias (default: 10)",
    )
    parser.add_argument(
        "--test-frame",
        action="store_true",
        help="No camera: ship one synthetic whiteboard frame and exit (validates the whole path)",
    )
    args = parser.parse_args(argv)
    if not args.list_devices and not args.class_id:
        parser.error("--class is required (unless using --list-devices)")
    if args.poll <= 0:
        parser.error("--poll must be positive")
    if args.send_interval <= 0:
        parser.error("--send-interval must be positive")
    if args.lost_delay <= 0:
        parser.error("--lost-delay must be positive")
    if not 0 <= args.privacy_min_confidence <= 1:
        parser.error("--privacy-min-confidence must be between 0 and 1")

    env_zones = os.getenv("CAMERA_AUDIENCE_ZONES")
    audience_zones = (
        tuple(args.audience_zone)
        if args.audience_zone
        else tuple(_parse_zone(zone) for zone in env_zones.split("|") if zone.strip())
        if env_zones
        else DEFAULT_AUDIENCE_ZONES
    )

    cfg = Config(
        base_url=args.base_url.rstrip("/"),
        token=args.token or None,
        class_id=args.class_id,
        class_title=args.class_title,
        lecture_title=args.lecture_title,
        force_new=False,  # the camera never opens a new lecture over a live one
        model_size="-",  # unused: no audio in this agent
        chunk_seconds=DEFAULT_CHUNK_SECONDS,
        language=None,
        device=None,
    )
    opts = CameraOptions(
        device=args.device,
        modality=args.modality,
        poll_seconds=args.poll,
        min_send_seconds=args.send_interval,
        track=args.track,
        preview=args.preview,
        pan=args.pan,
        tilt=args.tilt,
        zoom=args.zoom,
        auto_aim=args.auto_aim,
        flip_180=args.flip_180,
        follow_teacher=args.follow_teacher or args.track,
        follow_local=args.follow_local,
        lost_delay_seconds=args.lost_delay,
        share_with_zoom=args.share_with_zoom,
        pan_sign=args.pan_sign,
        tilt_sign=args.tilt_sign,
        audience_zones=audience_zones,
        privacy_min_person_confidence=args.privacy_min_confidence,
    )
    return cfg, opts, bool(args.test_frame), bool(args.list_devices)


def main(argv: list[str] | None = None) -> int:
    cfg, opts, test_frame, list_devices = _build(argv)

    if list_devices:
        from .camera import probe_devices

        print("[camera] probing devices 0-9 (a few seconds) …", flush=True)
        found = probe_devices()
        if not found:
            print("[camera] no camera opened on any of indices 0-9.", flush=True)
            return 1
        for index, w, h, ptz in found:
            tag = " (PTZ)" if ptz else ""
            print(f"  --device {index}  ->  {w}x{h}{tag}", flush=True)
        print(
            "[camera] pick one with --device N; run twice (board + slide) to cover both.",
            flush=True,
        )
        return 0

    gateway = Gateway(cfg)

    print(f"[camera] class '{cfg.class_id}' — asking {cfg.base_url} …", flush=True)
    try:
        started = gateway.start()
    except requests.RequestException as error:
        print(
            f"[camera] could not reach Harbour.Wiki: {error}",
            file=sys.stderr,
            flush=True,
        )
        return 1
    verb = "joining live" if started.resumed else "starting"
    print(
        f"[camera] {verb} lecture #{started.lecture} (session {started.session})",
        flush=True,
    )
    stream_modality = "board" if opts.modality == "desk" else opts.modality
    if opts.modality == "desk":
        print(
            "[camera] '--modality desk' is deprecated; tracking the lecturer "
            "but ingesting the writing surface as modality 'board'",
            flush=True,
        )

    if test_frame:
        from .camera import encode_jpeg_b64, make_test_board

        print("[camera] shipping one synthetic test frame …", flush=True)
        result = gateway.send_frame(
            encode_jpeg_b64(make_test_board()),
            stream_modality,
            datetime.now(timezone.utc),
        )
        print(f"[camera] server said: {result}", flush=True)
        print(
            f"[camera] check the lecture in the wiki — the drawn text should appear as a "
            f"'{stream_modality}' event after fusion.",
            flush=True,
        )
        return 0

    print(
        f"[camera] watching '{opts.modality}' on device {opts.device} — ships the best board "
        f"frame every {opts.min_send_seconds:g}s. Ctrl+C to stop.",
        flush=True,
    )

    def send(image_b64: str, captured_at: datetime) -> dict:
        return gateway.send_frame(image_b64, stream_modality, captured_at)

    def persist(image_b64: str, captured_at: datetime) -> str:
        return gateway.queue_frame(image_b64, stream_modality, captured_at)

    try:
        sent = run_agent(
            opts,
            send,
            locate_target=gateway.locate_target
            if (opts.auto_aim or opts.follow_teacher)
            else None,
            persist_frame=persist,
            drain_pending=gateway.drain_outbox,
        )
        print(f"[camera] done — {sent} frames shipped.", flush=True)
    except KeyboardInterrupt:
        print("\n[camera] stopped.", flush=True)
    # No flush here: the AUDIO recorder owns the lecture lifecycle; the camera
    # is a second stream into the same session and must not finalize it.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
