"""The storage contract every backend fulfils, run against each of them.

Redis runs on fakeredis; NATS needs a server and is skipped without one (see the
`nats_url` fixture).
"""

from unittest.mock import patch

import fakeredis
import pytest
from compas_model.models import Model

from antikythera.models import Blueprint
from antikythera.models import BlueprintSession
from antikythera.models import Task
from antikythera_orchestrator import InMemoryStorage
from antikythera_orchestrator import RedisStorage
from antikythera_orchestrator.storage.exceptions import RequestedBlueprintNotFound
from antikythera_orchestrator.storage.exceptions import RequestedModelNotFound
from antikythera_orchestrator.storage.exceptions import RequestedSessionNotFound


@pytest.fixture(params=["memory", "redis", "nats"])
def storage(request):
    if request.param == "memory":
        yield InMemoryStorage()
    elif request.param == "redis":
        server = fakeredis.FakeServer()
        with patch(
            "antikythera_orchestrator.storage.redis_storage._create_redis_client",
            side_effect=lambda db: fakeredis.FakeRedis(server=server, db=db, decode_responses=False),
        ):
            yield RedisStorage()
    else:
        yield request.getfixturevalue("nats_storage")


def _blueprint(blueprint_id="bp", name="BP"):
    start, end = Task(id="start", type="system.start"), Task(id="end", type="system.end")
    start >> end
    return Blueprint(id=blueprint_id, name=name, tasks=[start, end])


def test_session_data_round_trips_and_is_copied(storage):
    sessions = storage.session_storage("s")
    sessions.set("bp", "items", [1, 2])
    sessions.set_all("bp", {"a": {"x": 1}, "b": "text"})
    sessions.set("other_bp", "items", "elsewhere")

    sessions.get("bp", "items").append(3)

    assert sessions.get("bp", "items") == [1, 2]
    assert sessions.get_all("bp") == {"items": [1, 2], "a": {"x": 1}, "b": "text"}
    assert sessions.get("bp", "missing") is None
    assert storage.session_storage("another").get_all("bp") == {}


def test_session_lifecycle(storage):
    blueprint = _blueprint()
    for bsid in ("one", "two"):
        storage.session_storage(bsid).save_session(BlueprintSession(bsid=bsid, blueprint=blueprint))

    sessions = storage.session_storage("one")
    started_at = sessions.load_session_with_metadata()["started_at"]
    sessions.save_session(sessions.load_session())

    assert sessions.load_session().bsid == "one"
    assert sessions.load_session_with_metadata()["started_at"] == started_at
    assert storage.list_sessions() == ["two", "one"]
    assert storage.list_sessions(newest_first=False, limit=1) == ["one"]

    sessions.set("bp", "key", 1)
    sessions.remove_session()
    assert sessions.load_session() is None
    assert sessions.get("bp", "key") is None
    assert storage.list_sessions() == ["two"]
    with pytest.raises(RequestedSessionNotFound):
        sessions.remove_session()


def test_blueprints(storage):
    with storage.blueprint_storage() as blueprints:
        blueprints.add_blueprint(_blueprint("first", "First"))
        blueprints.add_blueprint(_blueprint("second", "Second"))

        assert blueprints.get_blueprint("first").name == "First"
        assert [item["id"] for item in blueprints.list_blueprints()] == ["first", "second"]
        assert blueprints.list_blueprints()[0]["task_count"] == 2

        blueprints.remove_blueprint("first")
        assert [item["id"] for item in blueprints.list_blueprints()] == ["second"]
        with pytest.raises(RequestedBlueprintNotFound):
            blueprints.get_blueprint("first")
        with pytest.raises(RequestedBlueprintNotFound):
            blueprints.remove_blueprint("first")


def test_models_and_nestings(storage):
    with storage.model_storage() as models:
        models.add_model("m1", Model())
        models.add_model("m2", Model())
        models.add_nesting("m1", {"stocks": []})

        assert models.list_models() == ["m1", "m2"]
        assert isinstance(models.get_model("m1"), Model)
        assert models.get_nesting("m1") == {"stocks": []}
        assert models.get_nesting("m2") is None

        models.remove_model("m1")
        assert models.list_models() == ["m2"]
        assert models.get_nesting("m1") is None
        with pytest.raises(RequestedModelNotFound):
            models.get_model("m1")
        with pytest.raises(RequestedModelNotFound):
            models.remove_model("m1")
        with pytest.raises(RequestedModelNotFound):
            models.add_nesting("m1", {})


def test_create_storage_by_name():
    from antikythera_orchestrator import create_storage

    assert isinstance(create_storage("memory"), InMemoryStorage)
    assert isinstance(create_storage("redis"), RedisStorage)
    with pytest.raises(ValueError, match="Unknown storage"):
        create_storage("floppy")


def test_create_transport_rejects_unknown_kinds():
    from antikythera.transport import create_transport

    with pytest.raises(ValueError, match="Unknown transport"):
        create_transport("carrier-pigeon")
