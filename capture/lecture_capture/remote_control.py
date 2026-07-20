"""Heartbeat and remote-command transport for the classroom scheduler."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import requests
from dotenv import load_dotenv


@dataclass(frozen=True)
class RemoteCommand:
    id: int
    kind: str
    payload: dict


class RemoteControlClient:
    def __init__(self, base_url: str, token: str | None) -> None:
        self.url = f"{base_url.rstrip('/')}/api/capture/heartbeat"
        self.headers = {"Content-Type": "application/json"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    @classmethod
    def from_workdir(cls, workdir: Path) -> "RemoteControlClient | None":
        load_dotenv(workdir / ".env")
        load_dotenv()
        base_url = os.getenv("HARBOUR_WIKI_BASE_URL", "").strip()
        if not base_url:
            return None
        return cls(base_url, os.getenv("CAPTURE_TOKEN"))

    def heartbeat(self, status: dict, command_results: list[dict]) -> list[RemoteCommand]:
        response = requests.post(
            self.url,
            json={**status, "commandResults": command_results},
            headers=self.headers,
            timeout=15,
        )
        response.raise_for_status()
        body = response.json()
        return [
            RemoteCommand(
                id=int(item["id"]),
                kind=str(item["kind"]),
                payload=dict(item.get("payload") or {}),
            )
            for item in body.get("commands") or []
        ]
