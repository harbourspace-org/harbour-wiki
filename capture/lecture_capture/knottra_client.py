"""Thin HTTP client for Knottra's ingest API (X-API-Key auth).

Mirrors the three calls the capture loop needs: claim the session (PUT config),
append speech events (POST events), and flush at the end.
"""

from __future__ import annotations

from datetime import datetime

import requests

from .config import Config

_TIMEOUT_SECONDS = 30


class KnottraClient:
    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._headers = {
            "X-API-Key": cfg.api_key,
            "Content-Type": "application/json",
        }

    def ensure_session(self) -> None:
        """Create/claim the session for this key by setting its fusion config."""
        response = requests.put(
            self._cfg.config_url,
            json={"domain_prompt": self._cfg.domain_prompt},
            headers=self._headers,
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

    def send_speech(self, content: str, confidence: float, when: datetime) -> None:
        # The events endpoint accepts a batch; we send one event per chunk.
        event = {
            "timestamp": when.isoformat(),
            "modality": "speech",
            "content": content,
            "confidence": round(confidence, 3),
        }
        response = requests.post(
            self._cfg.events_url,
            json=[event],
            headers=self._headers,
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

    def flush(self) -> None:
        response = requests.post(
            self._cfg.flush_url,
            headers=self._headers,
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
