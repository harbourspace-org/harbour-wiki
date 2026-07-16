"""Small durable FIFO for capture events.

Network delivery is deliberately downstream of this SQLite write: once an
utterance or board frame has been accepted by :class:`DurableOutbox`, a Wi-Fi
outage or process restart cannot make it disappear.  Multiple capture
processes may share the same database; server-side ``client_event_id``
deduplication makes concurrent/repeated delivery safe.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


def default_outbox_path() -> Path:
    configured = os.getenv("LECTURE_OUTBOX_PATH")
    if configured:
        return Path(configured)
    return Path.home() / ".lecture-capture" / "outbox.sqlite3"


@dataclass(frozen=True)
class OutboxItem:
    event_id: str
    endpoint: str
    payload: dict


class DurableOutbox:
    """SQLite-backed, process-safe at-least-once delivery queue."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_outbox_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_events (
                    event_id TEXT PRIMARY KEY,
                    endpoint TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_ns INTEGER NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10.0)

    def enqueue(self, event_id: str, endpoint: str, payload: dict) -> bool:
        """Persist an event; return False when that id was already queued."""
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._connect() as db:
            cursor = db.execute(
                """
                INSERT OR IGNORE INTO pending_events
                    (event_id, endpoint, payload_json, created_ns)
                VALUES (?, ?, ?, ?)
                """,
                (event_id, endpoint, encoded, time.time_ns()),
            )
        return cursor.rowcount == 1

    def contains(self, event_id: str) -> bool:
        with self._connect() as db:
            row = db.execute(
                "SELECT 1 FROM pending_events WHERE event_id = ?", (event_id,)
            ).fetchone()
        return row is not None

    def pending_count(self) -> int:
        with self._connect() as db:
            value = db.execute("SELECT COUNT(*) FROM pending_events").fetchone()[0]
        return int(value)

    def _oldest(self) -> OutboxItem | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT event_id, endpoint, payload_json
                FROM pending_events
                ORDER BY created_ns, event_id
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        return OutboxItem(row[0], row[1], json.loads(row[2]))

    def drain(
        self,
        deliver: Callable[[str, dict], object],
        *,
        max_items: int = 200,
    ) -> int:
        """Deliver FIFO entries, stopping on the first transport failure.

        The delete happens only after ``deliver`` returns successfully. If the
        remote commit succeeded but its response was lost, the retained event
        is retried with the same id and deduplicated by Knottra.
        """
        delivered = 0
        while delivered < max_items:
            item = self._oldest()
            if item is None:
                break
            deliver(item.endpoint, item.payload)
            with self._connect() as db:
                db.execute(
                    "DELETE FROM pending_events WHERE event_id = ?", (item.event_id,)
                )
            delivered += 1
        return delivered
