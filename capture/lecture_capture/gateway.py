"""HTTP client for Harbour.Wiki's ingest gateway (`POST /api/ingest`).

The lifecycle: ``start`` announces the class and receives the lecture/session
the gateway decided on; ``send_speech`` streams chunks into that session;
``flush`` finalizes. The recorder only carries the capture token — Harbour.Wiki
forwards to Knottra with its own key.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import requests

from .config import Config
from .outbox import DurableOutbox

_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class StartedLecture:
    session: str
    lecture: int
    resumed: bool
    vocabulary: tuple[str, ...] = ()


class Gateway:
    def __init__(
        self,
        cfg: Config,
        *,
        outbox: DurableOutbox | None = None,
        outbox_path: str | Path | None = None,
    ) -> None:
        self._cfg = cfg
        self._session: str | None = None
        self._outbox = outbox or DurableOutbox(outbox_path)
        self._headers = {"Content-Type": "application/json"}
        if cfg.token:
            self._headers["Authorization"] = f"Bearer {cfg.token}"

    def _post(self, body: dict) -> dict:
        response = requests.post(
            self._cfg.ingest_url,
            json=body,
            headers=self._headers,
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()

    def _deliver_outbox(self, endpoint: str, payload: dict) -> dict:
        url = (
            self._cfg.ingest_url
            if endpoint == "ingest"
            else f"{self._cfg.base_url}/api/vision"
        )
        timeout = _TIMEOUT_SECONDS if endpoint == "ingest" else 90
        response = requests.post(
            url,
            json=payload,
            headers=self._headers,
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()

    def drain_outbox(self, *, max_items: int = 200) -> int:
        return self._outbox.drain(self._deliver_outbox, max_items=max_items)

    def _event_id(
        self,
        modality: str,
        when: datetime,
        content_fingerprint: str,
    ) -> str:
        if self._session is None:
            raise RuntimeError("Gateway.start() must succeed before sending events")
        raw = (
            f"v1\0{self._session}\0{modality}\0{when.isoformat()}\0"
            f"{content_fingerprint}"
        ).encode()
        return "capture_" + hashlib.sha256(raw).hexdigest()[:48]

    def start(self, adopt_session: bool = True) -> StartedLecture:
        """Announce 'class X is recording now'; the gateway picks the lecture.

        ``adopt_session=False`` is for mid-run vocabulary refreshes: use the
        response's vocabulary but never switch which session we stream into.
        """
        course: dict = {"id": self._cfg.class_id}
        if self._cfg.class_title:
            course["title"] = self._cfg.class_title
        body: dict = {"action": "start", "course": course}
        if adopt_session:
            if self._cfg.lecture_title:
                body["lectureTitle"] = self._cfg.lecture_title
            if self._cfg.force_new:
                body["forceNew"] = True
        else:
            # Vocabulary refresh: the gateway must never create or rename a
            # lecture on our behalf mid-run.
            body["refreshOnly"] = True
        data = self._post(body)
        if adopt_session or self._session is None:
            self._session = data["session"]
            # Replay anything a previous recorder instance durably queued.
            # A failure here must not turn a successful session handshake into
            # startup failure; the next event/flush will try again.
            try:
                self.drain_outbox()
            except requests.RequestException:
                pass
        return StartedLecture(
            session=data["session"],
            lecture=int(data["lecture"]),
            resumed=bool(data.get("resumed")),
            vocabulary=tuple(data.get("vocabulary") or []),
        )

    def send_speech(self, content: str, confidence: float, when: datetime) -> None:
        if self._session is None:
            raise RuntimeError("Gateway.start() must succeed before sending speech")
        event_id = self._event_id(
            "speech", when, hashlib.sha256(content.encode()).hexdigest()
        )
        self._outbox.enqueue(
            event_id,
            "ingest",
            {
                "session": self._session,
                "events": [
                    {
                        "client_event_id": event_id,
                        "timestamp": when.isoformat(),
                        "modality": "speech",
                        "content": content,
                        "confidence": round(confidence, 3),
                    }
                ],
            },
        )
        self.drain_outbox()

    def send_frame(self, image_b64: str, modality: str, when: datetime) -> dict:
        """Ship a frame to /api/vision for multimodal fusion in Knottra.

        The gateway keeps the image intact; Knottra reads the instructional
        surface alongside speech from the same temporal window.
        """
        event_id = self.queue_frame(image_b64, modality, when)
        self.drain_outbox()
        return {
            "status": "ok",
            "ingested": 0 if self._outbox.contains(event_id) else 1,
            "pending": self._outbox.pending_count(),
        }

    def queue_frame(self, image_b64: str, modality: str, when: datetime) -> str:
        """Durably persist a frame without waiting for HTTP delivery."""
        if self._session is None:
            raise RuntimeError("Gateway.start() must succeed before sending frames")
        image_digest = hashlib.sha256(image_b64.encode()).hexdigest()
        event_id = self._event_id(modality, when, image_digest)
        self._outbox.enqueue(
            event_id,
            "vision",
            {
                "session": self._session,
                "modality": modality,
                "image": image_b64,
                "timestamp": when.isoformat(),
                "clientEventId": event_id,
            },
        )
        return event_id

    def locate_target(self, image_b64: str, target: str) -> dict:
        """Ask the server's LLM where the board/screen is in a room shot.
        Returns {found, bbox: [x,y,w,h] normalized 0..1 | None, confidence}."""
        response = requests.post(
            f"{self._cfg.base_url}/api/aim",
            json={"target": target, "image": image_b64},
            headers=self._headers,
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    def flush(self) -> None:
        if self._session is None:
            return
        self.drain_outbox(max_items=10_000)
        if self._outbox.pending_count():
            raise requests.ConnectionError("capture outbox still has pending events")
        self._post({"session": self._session, "flush": True})
