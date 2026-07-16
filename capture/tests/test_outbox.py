from datetime import datetime, timezone

import pytest
import requests

from lecture_capture.config import Config
from lecture_capture.gateway import Gateway
from lecture_capture.outbox import DurableOutbox


def config() -> Config:
    return Config(
        base_url="https://wiki.example",
        token="secret",
        class_id="algorithms",
        class_title=None,
        lecture_title=None,
        force_new=False,
        model_size="-",
        chunk_seconds=12,
        language=None,
        device=None,
    )


class Response:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


def test_outbox_is_durable_and_deduplicates_ids(tmp_path):
    path = tmp_path / "outbox.sqlite3"
    first = DurableOutbox(path)
    assert first.enqueue("event-123", "ingest", {"value": 1})
    assert not first.enqueue("event-123", "ingest", {"value": 2})
    reopened = DurableOutbox(path)
    delivered = []
    assert (
        reopened.drain(lambda endpoint, payload: delivered.append((endpoint, payload)))
        == 1
    )
    assert delivered == [("ingest", {"value": 1})]
    assert reopened.pending_count() == 0


def test_gateway_retries_same_client_event_id_after_timeout(monkeypatch, tmp_path):
    attempts = []
    online = False

    def post(url, json, headers, timeout):
        nonlocal online
        if json.get("action") == "start":
            return Response(
                {"session": "algorithms--l01", "lecture": 1, "resumed": False}
            )
        attempts.append(json)
        if not online:
            online = True
            raise requests.Timeout("response lost")
        return Response({"status": "ok", "ingested": 1})

    monkeypatch.setattr(requests, "post", post)
    gateway = Gateway(config(), outbox_path=tmp_path / "outbox.sqlite3")
    gateway.start()
    when = datetime(2026, 7, 16, 10, 0, tzinfo=timezone.utc)
    with pytest.raises(requests.Timeout):
        gateway.send_speech("Dijkstra relaxes an edge", 0.9, when)
    assert gateway._outbox.pending_count() == 1

    gateway.drain_outbox()
    assert gateway._outbox.pending_count() == 0
    first_id = attempts[0]["events"][0]["client_event_id"]
    second_id = attempts[1]["events"][0]["client_event_id"]
    assert first_id == second_id
