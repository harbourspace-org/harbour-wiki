"""HTTP client for Harbour.Wiki's ingest gateway (`POST /api/ingest`).

All three operations the capture loop needs — claim the session, append speech,
flush — go through this one endpoint. Harbour.Wiki forwards to Knottra with its
own key; the recorder only carries the capture token.
"""

from __future__ import annotations

from datetime import datetime

import requests

from .config import Config

_TIMEOUT_SECONDS = 30


class Gateway:
    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._headers = {"Content-Type": "application/json"}
        if cfg.token:
            self._headers["Authorization"] = f"Bearer {cfg.token}"

    def _post(self, body: dict) -> None:
        response = requests.post(
            self._cfg.ingest_url,
            json={"session": self._cfg.session_id, **body},
            headers=self._headers,
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

    def ensure_session(self) -> None:
        """Create/claim the session, set its config, and register it as a course."""
        self._post(
            {
                "domainPrompt": self._cfg.domain_prompt,
                "course": {"id": self._cfg.course_id, "title": self._cfg.course_title},
                "label": self._cfg.label,
            }
        )

    def send_speech(self, content: str, confidence: float, when: datetime) -> None:
        self._post(
            {
                "events": [
                    {
                        "timestamp": when.isoformat(),
                        "modality": "speech",
                        "content": content,
                        "confidence": round(confidence, 3),
                    }
                ]
            }
        )

    def flush(self) -> None:
        self._post({"flush": True})
