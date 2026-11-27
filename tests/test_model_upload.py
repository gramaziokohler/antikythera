"""Tests for POST /models/upload."""

import json
from unittest.mock import patch

import fakeredis
import pytest
from compas.data import json_dumps
from compas_model.models import Model
from fastapi.testclient import TestClient

from antikythera_orchestrator.api import app


@pytest.fixture()
def client():
    server = fakeredis.FakeServer()
    with patch(
        "antikythera_orchestrator.storage.redis_storage._create_redis_client",
        side_effect=lambda db: fakeredis.FakeRedis(server=server, db=db, decode_responses=False),
    ):
        with TestClient(app) as c:
            yield c


def _upload(client, text, filename="model.json"):
    return client.post("/models/upload", files={"file": (filename, text, "application/json")})


def test_compas_model_uploads(client):
    resp = _upload(client, json_dumps(Model()))

    assert resp.status_code == 201
    assert resp.json()["model_ids"][0] in client.get("/models").json()


def test_model_of_a_package_that_is_not_installed_names_the_package(client):
    model = json.loads(json_dumps(Model()))
    model["dtype"] = "not_installed_domain.model/DomainModel"

    resp = _upload(client, json.dumps(model))

    assert resp.status_code == 400
    assert "not_installed_domain" in resp.json()["detail"]
    assert "Install it" in resp.json()["detail"]
