"""HTTP client for Harbour.Wiki's ingest gateway (`POST /api/ingest`).

The lifecycle: ``start`` announces the class and receives the lecture/session
the gateway decided on; ``send_speech`` streams chunks into that session;
``flush`` finalizes. The recorder only carries the capture token — Harbour.Wiki
forwards to Knottra with its own key.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import requests

from .config import Config

_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class StartedLecture:
    session: str
    lecture: int
    resumed: bool


class Gateway:
    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._session: str | None = None
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

    def start(self) -> StartedLecture:
        """Announce 'class X is recording now'; the gateway picks the lecture."""
        course: dict = {"id": self._cfg.class_id}
        if self._cfg.class_title:
            course["title"] = self._cfg.class_title
        body: dict = {"action": "start", "course": course}
        if self._cfg.lecture_title:
            body["lectureTitle"] = self._cfg.lecture_title
        if self._cfg.force_new:
            body["forceNew"] = True
        data = self._post(body)
        self._session = data["session"]
        return StartedLecture(
            session=data["session"],
            lecture=int(data["lecture"]),
            resumed=bool(data.get("resumed")),
        )

    def send_speech(self, content: str, confidence: float, when: datetime) -> None:
        if self._session is None:
            raise RuntimeError("Gateway.start() must succeed before sending speech")
        self._post(
            {
                "session": self._session,
                "events": [
                    {
                        "timestamp": when.isoformat(),
                        "modality": "speech",
                        "content": content,
                        "confidence": round(confidence, 3),
                    }
                ],
            }
        )

    def send_frame(self, image_b64: str, modality: str, when: datetime) -> dict:
        """Ship a camera frame to /api/vision; the server extracts its text and
        ingests it into this session. Returns the server's summary."""
        if self._session is None:
            raise RuntimeError("Gateway.start() must succeed before sending frames")
        response = requests.post(
            f"{self._cfg.base_url}/api/vision",
            json={
                "session": self._session,
                "modality": modality,
                "image": image_b64,
                "timestamp": when.isoformat(),
            },
            headers=self._headers,
            timeout=90,  # vision extraction is slower than ingest
        )
        response.raise_for_status()
        return response.json()

    def flush(self) -> None:
        if self._session is None:
            return
        self._post({"session": self._session, "flush": True})
