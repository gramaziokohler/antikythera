"""Tests for re-running a session that already reached a terminal state."""

from unittest.mock import patch

import fakeredis
import pytest
from compas_eve.codecs import ProtobufMessageCodec
from compas_eve.memory import InMemoryTransport
from fastapi.testclient import TestClient

from antikythera.models import Blueprint
from antikythera.models import BlueprintSession
from antikythera.models import BlueprintSessionState
from antikythera.models import Task
from antikythera.models import TaskState
from antikythera_orchestrator import api
from antikythera_orchestrator.api import app
from antikythera_orchestrator.storage import BlueprintStorage
from antikythera_orchestrator.storage import SessionStorage

BLUEPRINT_ID = "bp-restart-test"
SESSION_ID = "session-that-finished"


@pytest.fixture()
def mock_redis():
    server = fakeredis.FakeServer()

    def fake_create(db: int):
        return fakeredis.FakeRedis(server=server, db=db, decode_responses=False)

    with patch("antikythera_orchestrator.storage.redis_storage._create_redis_client", side_effect=fake_create):
        yield


@pytest.fixture()
def client(mock_redis):
    transport = InMemoryTransport(codec=ProtobufMessageCodec())
    with patch("antikythera_orchestrator.orchestrator._get_eve_transport", return_value=transport):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c

    # A restart starts an orchestrator for real, so its threads have to go.
    for active in list(api._sessions.values()):
        active.orchestrator.stop()
    api._sessions.clear()


def _blueprint() -> Blueprint:
    start = Task(id="start", type="system.start")
    end = Task(id="end", type="system.end")
    start >> end
    return Blueprint(id=BLUEPRINT_ID, name="restart test", version="1", tasks=[start, end])


def _seed_completed_session(params: dict | None = None) -> None:
    """Store a session in the state a successful run leaves behind."""
    blueprint = _blueprint()
    with BlueprintStorage() as storage:
        storage.add_blueprint(blueprint)

    for task in blueprint.tasks:
        task.state = TaskState.SUCCEEDED

    session = BlueprintSession(
        bsid=SESSION_ID,
        blueprint=blueprint,
        params=params or {},
        state=BlueprintSessionState.COMPLETED,
    )
    with SessionStorage(SESSION_ID) as storage:
        storage.save_session(session)


def _stored(session_id: str) -> BlueprintSession:
    with SessionStorage(session_id) as storage:
        return storage.load_session()


class TestStartOnCompletedSession:
    def test_start_is_rejected_rather_than_silently_doing_nothing(self, client):
        """A completed session has no schedulable tasks, so start() is a no-op.

        It used to answer 200 "Session started." while nothing ran at all.
        """
        _seed_completed_session()

        response = client.post(f"/sessions/{SESSION_ID}/start", json={})

        assert response.status_code == 409
        assert "restart" in response.json()["detail"]


class TestRestartSession:
    def test_restart_runs_under_a_new_session_id(self, client):
        _seed_completed_session()

        response = client.post(f"/sessions/{SESSION_ID}/restart")

        assert response.status_code == 202
        new_session_id = response.json()["session_id"]
        assert new_session_id != SESSION_ID
        assert _stored(new_session_id) is not None

    def test_restart_leaves_the_finished_session_alone(self, client):
        _seed_completed_session()

        client.post(f"/sessions/{SESSION_ID}/restart")

        previous = _stored(SESSION_ID)
        assert previous.state == BlueprintSessionState.COMPLETED
        assert [t.state for t in previous.blueprint.tasks] == [TaskState.SUCCEEDED, TaskState.SUCCEEDED]

    def test_restarted_session_starts_from_scratch(self, client):
        _seed_completed_session()

        new_session_id = client.post(f"/sessions/{SESSION_ID}/restart").json()["session_id"]

        restarted = _stored(new_session_id)
        assert TaskState.SUCCEEDED not in [t.state for t in restarted.blueprint.tasks]

    def test_restart_carries_the_session_params_over(self, client):
        _seed_completed_session(params={"span": "4200"})

        new_session_id = client.post(f"/sessions/{SESSION_ID}/restart").json()["session_id"]

        assert _stored(new_session_id).params == {"span": "4200"}

    def test_restarting_a_running_session_is_rejected(self, client):
        _seed_completed_session()
        new_session_id = client.post(f"/sessions/{SESSION_ID}/restart").json()["session_id"]

        response = client.post(f"/sessions/{new_session_id}/restart")

        assert response.status_code == 409
        assert "running" in response.json()["detail"].lower()

    def test_restarting_an_unknown_session_is_a_404(self, client):
        response = client.post("/sessions/no-such-session/restart")

        assert response.status_code == 404
