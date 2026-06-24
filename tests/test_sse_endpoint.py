"""Tests for GET /sessions/{id}/stream SSE endpoint."""

import asyncio
import threading
from unittest.mock import patch

import fakeredis
import pytest
from fastapi.testclient import TestClient

from antikythera.models import BlueprintSessionState
from antikythera_orchestrator.api import _push_sse_event
from antikythera_orchestrator.api import _register_sse_callbacks
from antikythera_orchestrator.api import _sse_listeners
from antikythera_orchestrator.api import _sse_listeners_lock
from antikythera_orchestrator.api import app


@pytest.fixture()
def mock_redis():
    server = fakeredis.FakeServer()

    def fake_create(db: int):
        return fakeredis.FakeRedis(server=server, db=db, decode_responses=False)

    with patch("antikythera_orchestrator.storage.redis_storage._create_redis_client", side_effect=fake_create):
        yield


@pytest.fixture()
def client(mock_redis):
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def _seed_session(session_id: str):
    """Store a minimal session so the SSE endpoint can find it."""
    from antikythera.models import Blueprint
    from antikythera.models import BlueprintSession
    from antikythera.models import Task
    from antikythera_orchestrator.storage import SessionStorage

    start = Task(id="start", type="system.start")
    end = Task(id="end", type="system.end")
    start >> end
    bp = Blueprint(id="bp-sse-test", name="test", version="1", tasks=[start, end])
    session = BlueprintSession(bsid=session_id, blueprint=bp)
    with SessionStorage(session_id) as s:
        s.save_session(session)


class TestSseNotFound:
    def test_missing_session_returns_404(self, client):
        resp = client.get("/sessions/does-not-exist/stream")
        assert resp.status_code == 404


def _wait_for_listener(session_id: str, timeout: float = 2.0) -> None:
    """Block until at least one SSE listener is registered for session_id."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with _sse_listeners_lock:
            if _sse_listeners.get(session_id):
                return
        time.sleep(0.005)
    raise TimeoutError(f"No SSE listener registered for {session_id!r} within {timeout}s")


class TestSseHeaders:
    def test_stream_returns_event_stream_content_type(self, client):
        session_id = "sse-hdr-test"
        _seed_session(session_id)

        def _close_stream():
            _wait_for_listener(session_id)
            with _sse_listeners_lock:
                for loop, q in _sse_listeners.get(session_id, []):
                    loop.call_soon_threadsafe(q.put_nowait, None)

        t = threading.Thread(target=_close_stream, daemon=True)
        t.start()

        with client.stream("GET", f"/sessions/{session_id}/stream") as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers["content-type"]

        t.join(timeout=2)


class TestSseEventDelivery:
    def test_push_delivers_task_state_event(self):
        session_id = "sse-task-deliver"
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        queue: asyncio.Queue = asyncio.Queue()

        with _sse_listeners_lock:
            _sse_listeners.setdefault(session_id, []).append((loop, queue))

        try:
            _push_sse_event(session_id, "task_state_changed", {"blueprint_id": "bp1", "task_id": "t1", "state": "RUNNING"})

            event = loop.run_until_complete(queue.get())
            assert event["event"] == "task_state_changed"
            assert event["data"] == {"blueprint_id": "bp1", "task_id": "t1", "state": "RUNNING"}
        finally:
            with _sse_listeners_lock:
                _sse_listeners.pop(session_id, None)
            asyncio.set_event_loop(None)
            loop.close()

    def test_push_delivers_session_state_event(self):
        session_id = "sse-sess-deliver"
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        queue: asyncio.Queue = asyncio.Queue()

        with _sse_listeners_lock:
            _sse_listeners.setdefault(session_id, []).append((loop, queue))

        try:
            _push_sse_event(session_id, "session_state_changed", {"state": "completed"})

            event = loop.run_until_complete(queue.get())
            assert event["event"] == "session_state_changed"
            assert event["data"]["state"] == "completed"
        finally:
            with _sse_listeners_lock:
                _sse_listeners.pop(session_id, None)
            asyncio.set_event_loop(None)
            loop.close()
    def test_push_with_no_listeners_is_silent(self):
        _push_sse_event("no-such-session", "session_state_changed", {"state": "running"})

    @pytest.mark.parametrize("terminal_state", [BlueprintSessionState.COMPLETED, BlueprintSessionState.FAILED])
    def test_terminal_session_state_closes_stream(self, terminal_state):
        from unittest.mock import MagicMock

        session_id = f"sse-terminal-{terminal_state}"
        loop = asyncio.new_event_loop()
        queue: asyncio.Queue = asyncio.Queue()

        with _sse_listeners_lock:
            _sse_listeners.setdefault(session_id, []).append((loop, queue))

        try:
            mock_orchestrator = MagicMock()
            captured_cb = {}

            def capture_session_cb(cb):
                captured_cb["fn"] = cb

            mock_orchestrator.register_session_state_callback.side_effect = capture_session_cb
            _register_sse_callbacks(session_id, mock_orchestrator)

            captured_cb["fn"](terminal_state)

            event = loop.run_until_complete(queue.get())
            assert event["event"] == "session_state_changed"
            assert event["data"]["state"] == str(terminal_state)

            sentinel = loop.run_until_complete(queue.get())
            assert sentinel is None
        finally:
            with _sse_listeners_lock:
                _sse_listeners.pop(session_id, None)
            loop.close()


class TestSseEventFormat:
    def test_stream_emits_correctly_formatted_sse_lines(self, client):
        session_id = "sse-fmt-test"
        _seed_session(session_id)

        collected = []

        def _push_and_close():
            import time

            _wait_for_listener(session_id)
            _push_sse_event(session_id, "session_state_changed", {"state": "completed"})
            time.sleep(0.05)
            with _sse_listeners_lock:
                for loop, q in _sse_listeners.get(session_id, []):
                    loop.call_soon_threadsafe(q.put_nowait, None)

        t = threading.Thread(target=_push_and_close, daemon=True)
        t.start()

        with client.stream("GET", f"/sessions/{session_id}/stream") as resp:
            for line in resp.iter_lines():
                if line:
                    collected.append(line)

        t.join(timeout=2)

        assert any("event: session_state_changed" in line for line in collected)
        assert any('"state": "completed"' in line for line in collected)


class TestDatastoreUpdatedEvent:
    def test_push_delivers_datastore_updated_event(self):
        session_id = "sse-ds-deliver"
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        queue: asyncio.Queue = asyncio.Queue()

        with _sse_listeners_lock:
            _sse_listeners.setdefault(session_id, []).append((loop, queue))

        try:
            _push_sse_event(
                session_id,
                "datastore_updated",
                {"blueprint_id": "bp1", "data": {"score": {"value": 99, "type": "number"}}},
            )

            event = loop.run_until_complete(queue.get())
            assert event["event"] == "datastore_updated"
            assert event["data"]["blueprint_id"] == "bp1"
            assert event["data"]["data"]["score"]["value"] == 99
        finally:
            with _sse_listeners_lock:
                _sse_listeners.pop(session_id, None)
            asyncio.set_event_loop(None)
            loop.close()
    def test_register_sse_callbacks_wires_datastore_update_callback(self, mock_redis):
        """Registering callbacks should include the datastore_updated callback."""
        from unittest.mock import MagicMock

        mock_orchestrator = MagicMock()
        session_id = "sse-ds-wire-test"

        _register_sse_callbacks(session_id, mock_orchestrator)

        # All three register_* methods must have been called
        mock_orchestrator.register_task_state_callback.assert_called_once()
        mock_orchestrator.register_session_state_callback.assert_called_once()
        mock_orchestrator.register_datastore_update_callback.assert_called_once()

    def test_datastore_update_callback_enriches_and_pushes(self, mock_redis):
        """The registered datastore callback enriches values and pushes SSE events."""
        import asyncio as _asyncio

        session_id = "sse-ds-enrich-test"
        loop = _asyncio.new_event_loop()
        _asyncio.set_event_loop(loop)
        queue: _asyncio.Queue = _asyncio.Queue()

        with _sse_listeners_lock:
            _sse_listeners.setdefault(session_id, []).append((loop, queue))

        try:
            from unittest.mock import MagicMock

            mock_orchestrator = MagicMock()
            captured_cb = {}

            def capture_datastore_cb(cb):
                captured_cb["fn"] = cb

            mock_orchestrator.register_datastore_update_callback.side_effect = capture_datastore_cb

            _register_sse_callbacks(session_id, mock_orchestrator)

            # Invoke the registered callback with raw (un-enriched) data
            captured_cb["fn"]("my-bp", {"score": 42, "label": "good"})

            event = loop.run_until_complete(queue.get())
            assert event["event"] == "datastore_updated"
            assert event["data"]["blueprint_id"] == "my-bp"
            # Values must be enriched with type info
            assert event["data"]["data"]["score"]["value"] == 42
            assert event["data"]["data"]["score"]["type"] == "number"
            assert event["data"]["data"]["label"]["value"] == "good"
            assert event["data"]["data"]["label"]["type"] == "text"
        finally:
            with _sse_listeners_lock:
                _sse_listeners.pop(session_id, None)
            _asyncio.set_event_loop(None)
            loop.close()
