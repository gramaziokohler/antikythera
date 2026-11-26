"""Running blueprints entirely in-process: in-memory transport and storage, no broker, no Redis."""

from typing import Any
from typing import Dict
from unittest.mock import patch

import pytest
from compas_eve.codecs import ProtobufMessageCodec
from compas_eve.memory import InMemoryTransport
from compas_model.elements import Element
from compas_model.models import Model

from antikythera.models import Blueprint
from antikythera.models import BlueprintSession
from antikythera.models import BlueprintSessionState
from antikythera.models import Task
from antikythera.models import TaskInput
from antikythera.models import TaskOutput
from antikythera.models import TaskParam
from antikythera_agents.base_agent import Agent
from antikythera_agents.decorators import agent
from antikythera_agents.decorators import tool
from antikythera_agents.launcher import AgentLauncher
from antikythera_orchestrator import InMemoryStorage
from antikythera_orchestrator import Orchestrator
from antikythera_orchestrator.storage.exceptions import RequestedBlueprintNotFound
from antikythera_orchestrator.storage.exceptions import RequestedModelNotFound
from antikythera_orchestrator.storage.exceptions import RequestedSessionNotFound


@agent(type="in_memory_test")
class InMemoryTestAgent(Agent):
    @tool(name="double")
    def double(self, task: Task) -> Dict[str, Any]:
        return {"result": task.get_input_value("val") * 2}

    @tool(name="visit")
    def visit(self, task: Task) -> Dict[str, Any]:
        return {"visited": task.context.get("element_id")}


@pytest.fixture
def no_infrastructure():
    """Fail loudly if anything tries to reach Redis or an MQTT broker."""

    def refuse(*args, **kwargs):
        raise AssertionError("in-process run must not touch Redis or MQTT")

    with (
        patch("antikythera_orchestrator.storage.redis_storage._create_redis_client", side_effect=refuse),
        patch("antikythera_orchestrator.orchestrator._get_eve_transport", side_effect=refuse),
        patch("antikythera_agents.launcher._get_eve_transport", side_effect=refuse),
    ):
        yield


def _run(session, storage, cleanup_manager, timeout=10):
    transport = InMemoryTransport(codec=ProtobufMessageCodec())
    launcher = cleanup_manager.register(AgentLauncher(transport=transport))
    launcher.agents["in_memory_test"] = InMemoryTestAgent()
    launcher.start()
    orchestrator = cleanup_manager.register(Orchestrator(session, transport=transport, storage=storage))
    orchestrator.start()
    assert orchestrator.await_completion(timeout=timeout)
    return orchestrator


def test_composite_blueprint_runs_in_process(no_infrastructure, cleanup_manager):
    storage = InMemoryStorage()

    inner_start = Task(id="inner_start", type="system.start")
    inner_task = Task(
        id="inner_task",
        type="in_memory_test.double",
        inputs=[TaskInput(name="val", get_from="inner_input")],
        outputs=[TaskOutput(name="result")],
    )
    inner_end = Task(id="inner_end", type="system.end")
    inner_start >> inner_task >> inner_end
    with storage.blueprint_storage() as blueprints:
        blueprints.add_blueprint(Blueprint(id="inner_bp", name="Inner", tasks=[inner_start, inner_task, inner_end]))

    start = Task(id="start", type="system.start")
    first = Task(id="first", type="in_memory_test.double", inputs=[TaskInput(name="val", value=5)], outputs=[TaskOutput(name="result")])
    composite = Task(
        id="composite",
        type="system.composite",
        params=[TaskParam(name="blueprint", value={"static": "inner_bp"})],
        inputs=[TaskInput(name="inner_input", get_from="result")],
        outputs=[TaskOutput(name="result", set_to="final_result")],
    )
    end = Task(id="end", type="system.end")
    start >> first >> composite >> end
    blueprint = Blueprint(id="outer_bp", name="Outer", tasks=[start, first, composite, end])

    orchestrator = _run(BlueprintSession(bsid="in_memory_composite", blueprint=blueprint), storage, cleanup_manager)

    assert orchestrator.session.state == BlueprintSessionState.COMPLETED
    with storage.session_storage("in_memory_composite") as session_storage:
        assert session_storage.get("outer_bp", "final_result") == 20
        assert session_storage.load_session().state == BlueprintSessionState.COMPLETED


def test_dynamic_expansion_reads_model_from_injected_storage(no_infrastructure, cleanup_manager):
    storage = InMemoryStorage()
    model = Model()
    elements = [Element(), Element(), Element()]
    for element in elements:
        model.add_element(element)
    with storage.model_storage() as models:
        models.add_model("model", model)

    inner_start = Task(id="inner_start", type="system.start")
    visit = Task(id="visit", type="in_memory_test.visit", outputs=[TaskOutput(name="visited")])
    inner_end = Task(id="inner_end", type="system.end")
    inner_start >> visit >> inner_end
    with storage.blueprint_storage() as blueprints:
        blueprints.add_blueprint(Blueprint(id="per_element", name="Per element", tasks=[inner_start, visit, inner_end]))

    start = Task(id="start", type="system.start")
    each = Task(
        id="each",
        type="system.composite",
        params=[TaskParam(name="blueprint", value={"dynamic": {"blueprint_id": "per_element", "sequencer": "basic_sequencer"}})],
        outputs=[TaskOutput(name="visited")],
    )
    end = Task(id="end", type="system.end")
    start >> each >> end
    blueprint = Blueprint(id="dynamic_bp", name="Dynamic", tasks=[start, each, end])
    session = BlueprintSession(bsid="in_memory_dynamic", blueprint=blueprint, params={"model_id": "model"})

    orchestrator = _run(session, storage, cleanup_manager)

    assert orchestrator.session.state == BlueprintSessionState.COMPLETED
    task_ids = {data["task"].id for _, data in orchestrator.graph.nodes(data=True)}
    assert {"each_0", "each_1", "each_2"} <= task_ids


def test_transport_without_protobuf_codec_is_rejected():
    session = BlueprintSession(bsid="json_codec", blueprint=_trivial_blueprint())
    with pytest.raises(ValueError, match="ProtobufMessageCodec"):
        Orchestrator(session, transport=InMemoryTransport(), storage=InMemoryStorage())
    with pytest.raises(ValueError, match="ProtobufMessageCodec"):
        AgentLauncher(transport=InMemoryTransport())


def _trivial_blueprint():
    start, end = Task(id="start", type="system.start"), Task(id="end", type="system.end")
    start >> end
    return Blueprint(id="bp", name="BP", tasks=[start, end])


def test_backends_do_not_share_state():
    first, second = InMemoryStorage(), InMemoryStorage()
    with first.model_storage() as models:
        models.add_model("m", Model())

    with first.model_storage() as models:
        assert models.list_models() == ["m"]
    with second.model_storage() as models:
        assert models.list_models() == []


def test_session_storage_returns_copies():
    storage = InMemoryStorage()
    sessions = storage.session_storage("s")
    sessions.set("bp", "items", [1, 2])

    sessions.get("bp", "items").append(3)

    assert sessions.get("bp", "items") == [1, 2]
    assert sessions.get_all("bp") == {"items": [1, 2]}
    assert sessions.get("bp", "missing") is None


def test_session_lifecycle():
    storage = InMemoryStorage()
    blueprint = _trivial_blueprint()
    for bsid in ("one", "two"):
        storage.session_storage(bsid).save_session(BlueprintSession(bsid=bsid, blueprint=blueprint))

    sessions = storage.session_storage("one")
    started_at = sessions.load_session_with_metadata()["started_at"]
    sessions.save_session(sessions.load_session())

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


def test_blueprint_and_model_not_found():
    storage = InMemoryStorage()
    with storage.blueprint_storage() as blueprints:
        with pytest.raises(RequestedBlueprintNotFound):
            blueprints.get_blueprint("nope")
        with pytest.raises(RequestedBlueprintNotFound):
            blueprints.remove_blueprint("nope")
    with storage.model_storage() as models:
        with pytest.raises(RequestedModelNotFound):
            models.get_model("nope")
        with pytest.raises(RequestedModelNotFound):
            models.add_nesting("nope", {})
        assert models.get_nesting("nope") is None
