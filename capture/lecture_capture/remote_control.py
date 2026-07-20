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


@dataclass(frozen=True)
class ScheduleUpdate:
    body: dict
    version: str


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


class ScheduleClient:
    """Pulls this agent's timetable from the wiki so recording can start on
    schedule with a schedule that is managed centrally, not on the lecture PC."""

    def __init__(self, base_url: str, token: str | None, agent_id: str) -> None:
        self.url = f"{base_url.rstrip('/')}/api/capture/schedule"
        self.agent_id = agent_id
        self.headers = {"Accept": "application/json"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    @classmethod
    def from_workdir(cls, workdir: Path, agent_id: str) -> "ScheduleClient | None":
        load_dotenv(workdir / ".env")
        load_dotenv()
        base_url = os.getenv("HARBOUR_WIKI_BASE_URL", "").strip()
        if not base_url:
            return None
        return cls(base_url, os.getenv("CAPTURE_TOKEN"), agent_id)

    def fetch(self, current_version: str | None) -> ScheduleUpdate | None:
        """Return the stored schedule only if it differs from ``current_version``
        (the version the agent is already running); ``None`` means unchanged."""
        params = {"agentId": self.agent_id}
        if current_version:
            params["version"] = current_version
        response = requests.get(
            self.url, params=params, headers=self.headers, timeout=15
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("changed"):
            return None
        return ScheduleUpdate(body=dict(data["schedule"]), version=str(data["version"]))
