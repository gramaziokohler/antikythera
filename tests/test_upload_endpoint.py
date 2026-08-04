"""Tests for POST /blueprints/upload."""

import json
from unittest.mock import patch

import fakeredis
import pytest
from fastapi.testclient import TestClient

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


def _blueprint(condition=None, while_condition=None, outputs=None):
    """start -> gate (scope) -> body -> gate_close -> end."""
    scope_start = {"while_policy": {"condition": while_condition}} if while_condition else {}
    body = {"id": "body", "type": "system.sleep", "outputs": outputs or [], "depends_on": [{"id": "gate"}]}
    if condition:
        body["condition"] = condition

    return {
        "version": "1.0",
        "id": "upload-test-bp",
        "name": "Upload Test",
        "tasks": [
            {"id": "start", "type": "system.start"},
            {"id": "gate", "type": "system.sleep", "scope_start": scope_start, "depends_on": [{"id": "start"}]},
            body,
            {"id": "gate_close", "type": "system.sleep", "scope_end": "gate", "depends_on": [{"id": "body"}]},
            {"id": "end", "type": "system.end", "depends_on": [{"id": "gate_close"}]},
        ],
    }


def _upload(client, blueprint, filename="blueprint.json"):
    return client.post(
        "/blueprints/upload",
        files={"file": (filename, json.dumps(blueprint), "application/json")},
    )


def _stored_ids(client):
    return [bp["id"] for bp in client.get("/blueprints").json()]


class TestUploadDataflowRejection:
    def test_rejects_while_condition_reading_an_unproduced_name(self, client):
        resp = _upload(client, _blueprint(while_condition="elements_remaining > 0"))

        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert detail["message"].startswith("Blueprint 'upload-test-bp' has 1 dataflow problem")
        assert len(detail["problems"]) == 1
        assert "elements_remaining" in detail["problems"][0]

    def test_rejected_blueprint_is_not_stored(self, client):
        _upload(client, _blueprint(while_condition="elements_remaining > 0"))

        assert "upload-test-bp" not in _stored_ids(client)

    def test_rejects_skip_condition_reading_an_unproduced_name(self, client):
        resp = _upload(client, _blueprint(condition="needs_processing"))

        assert resp.status_code == 400
        assert "needs_processing" in resp.json()["detail"]["problems"][0]

    def test_reports_every_problem_at_once(self, client):
        resp = _upload(client, _blueprint(condition="needs_processing", while_condition="elements_remaining > 0"))

        assert resp.status_code == 400
        assert len(resp.json()["detail"]["problems"]) == 2

    def test_accepts_a_condition_whose_name_a_task_produces(self, client):
        blueprint = _blueprint(while_condition="counter < 3", outputs=[{"name": "counter"}])

        resp = _upload(client, blueprint)

        assert resp.status_code == 201, resp.text
        assert resp.json()["blueprint_id"] == "upload-test-bp"
        assert "upload-test-bp" in _stored_ids(client)

    def test_accepts_a_blueprint_without_conditions(self, client):
        resp = _upload(client, _blueprint())

        assert resp.status_code == 201, resp.text
        assert "upload-test-bp" in _stored_ids(client)


class TestUploadRejectsMalformedInput:
    def test_rejects_non_json_extension(self, client):
        resp = client.post("/blueprints/upload", files={"file": ("blueprint.txt", "{}", "text/plain")})

        assert resp.status_code == 400
        assert "Only JSON files" in resp.json()["detail"]

    def test_rejects_unparsable_json(self, client):
        resp = client.post("/blueprints/upload", files={"file": ("blueprint.json", "not json", "application/json")})

        assert resp.status_code == 400
        assert "Failed to parse" in resp.json()["detail"]
