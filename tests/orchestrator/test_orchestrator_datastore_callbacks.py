"""Unit tests for the datastore update callback mechanism on Orchestrator."""

from antikythera.models import Blueprint
from antikythera.models import BlueprintSession
from antikythera.models import Task
from antikythera.models import TaskOutput
from antikythera.models import TaskParam
from antikythera_orchestrator.orchestrator import Orchestrator
from antikythera_orchestrator.orchestrator import _create_global_id


def _make_simple_orchestrator(mock_immudb, mock_transport_orchestrator, session_id: str) -> Orchestrator:
    start = Task(id="start", type="system.start")
    end = Task(id="end", type="system.end")
    start >> end
    bp = Blueprint(id="bp-cb-test", name="test", version="1", tasks=[start, end])
    session = BlueprintSession(bsid=session_id, blueprint=bp)
    return Orchestrator(session)


class TestPersistOutputs:
    def test_persist_outputs_writes_to_storage_and_fires_callback(self, mock_immudb, mock_transport_orchestrator):
        orch = _make_simple_orchestrator(mock_immudb, mock_transport_orchestrator, "sess-persist-1")

        received = []
        orch.register_datastore_update_callback(lambda bp, data: received.append((bp, data)))

        orch._persist_outputs("my-blueprint", {"result": 42, "name": "hello"})

        assert received == [("my-blueprint", {"result": 42, "name": "hello"})]
        assert orch.session_storage.get("my-blueprint", "result") == 42
        assert orch.session_storage.get("my-blueprint", "name") == "hello"

    def test_persist_outputs_does_not_fire_callback_for_empty_dict(self, mock_immudb, mock_transport_orchestrator):
        orch = _make_simple_orchestrator(mock_immudb, mock_transport_orchestrator, "sess-persist-2")

        received = []
        orch.register_datastore_update_callback(lambda bp, data: received.append((bp, data)))

        orch._persist_outputs("my-blueprint", {})

        assert received == []

    def test_persist_outputs_callback_exception_does_not_propagate(self, mock_immudb, mock_transport_orchestrator):
        orch = _make_simple_orchestrator(mock_immudb, mock_transport_orchestrator, "sess-persist-3")

        def bad_cb(bp, data):
            raise RuntimeError("boom")

        orch.register_datastore_update_callback(bad_cb)

        # Should not raise
        orch._persist_outputs("my-blueprint", {"key": "value"})


class TestMapOutputsToSession:
    def test_fires_callback_with_correct_blueprint_id_and_outputs(self, mock_immudb, mock_transport_orchestrator):
        orch = _make_simple_orchestrator(mock_immudb, mock_transport_orchestrator, "sess-map-1")

        received = []
        orch.register_datastore_update_callback(lambda bp, data: received.append((bp, data)))

        task = Task(id="worker", type="some.task", outputs=[TaskOutput(name="score", value=99)])
        orch._map_outputs_to_session("test-bp", task)

        assert len(received) == 1
        bp_id, data = received[0]
        assert bp_id == "test-bp"
        assert data == {"score": 99}

    def test_no_callback_when_task_has_no_outputs(self, mock_immudb, mock_transport_orchestrator):
        orch = _make_simple_orchestrator(mock_immudb, mock_transport_orchestrator, "sess-map-2")

        received = []
        orch.register_datastore_update_callback(lambda bp, data: received.append((bp, data)))

        task = Task(id="worker", type="some.task", outputs=[])
        orch._map_outputs_to_session("test-bp", task)

        assert received == []

    def test_respects_set_to_mapping(self, mock_immudb, mock_transport_orchestrator):
        orch = _make_simple_orchestrator(mock_immudb, mock_transport_orchestrator, "sess-map-3")

        received = []
        orch.register_datastore_update_callback(lambda bp, data: received.append((bp, data)))

        task = Task(
            id="worker",
            type="some.task",
            outputs=[TaskOutput(name="raw_result", set_to="final_score", value=77)],
        )
        orch._map_outputs_to_session("test-bp", task)

        assert received[0][1] == {"final_score": 77}


class TestMapOutputsToOuterSession:
    def test_non_dynamic_composite_fires_callback_with_outer_blueprint_id(self, mock_immudb, mock_transport_orchestrator):
        orch = _make_simple_orchestrator(mock_immudb, mock_transport_orchestrator, "sess-outer-1")

        received = []
        orch.register_datastore_update_callback(lambda bp, data: received.append((bp, data)))

        outer_bp_id = "outer-bp"
        inner_bp_id = "inner-bp"

        # Create a non-dynamic composite task (static inner blueprint reference)
        composite_task = Task(
            id="composite",
            type="system.composite",
            outputs=[TaskOutput(name="result")],
            params=[TaskParam(name="blueprint", value={"static": inner_bp_id})],
        )

        fqn = _create_global_id(outer_bp_id, composite_task)
        orch.session.composite_to_inner_blueprint_map[fqn] = inner_bp_id

        # Seed the inner blueprint's storage with the output value
        orch.session_storage.set(inner_bp_id, "result", "computed_value")

        orch._map_outputs_to_outer_session(outer_bp_id, composite_task)

        assert len(received) == 1
        bp_id, data = received[0]
        assert bp_id == outer_bp_id
        assert data == {"result": "computed_value"}

    def test_dynamic_composite_fires_callback_with_accumulated_dict(self, mock_immudb, mock_transport_orchestrator):
        orch = _make_simple_orchestrator(mock_immudb, mock_transport_orchestrator, "sess-outer-2")

        received = []
        orch.register_datastore_update_callback(lambda bp, data: received.append((bp, data)))

        outer_bp_id = "outer-bp"
        inner_bp_id = "inner-bp-elem1"
        element_id = "element-abc"

        # Dynamic composite task: blueprint param has dynamic.element with element_id
        blueprint_param = {
            "dynamic": {
                "blueprint_id": "some-bp",
                "element": {"element_id": element_id},
                "expanded": True,
            }
        }
        composite_task = Task(
            id="dyn-composite",
            type="system.composite",
            outputs=[TaskOutput(name="output")],
            params=[TaskParam(name="blueprint", value=blueprint_param)],
        )

        fqn = _create_global_id(outer_bp_id, composite_task)
        orch.session.composite_to_inner_blueprint_map[fqn] = inner_bp_id

        # Seed the inner storage with the output value
        orch.session_storage.set(inner_bp_id, "output", "elem_value")

        # Seed an existing accumulated dict in the outer storage (simulating a prior element)
        orch.session_storage.set(outer_bp_id, "output", {"element-prev": "prev_value"})

        orch._map_outputs_to_outer_session(outer_bp_id, composite_task)

        assert len(received) == 1
        bp_id, data = received[0]
        assert bp_id == outer_bp_id
        # Full accumulated dict, not just the new element
        assert data == {"output": {"element-prev": "prev_value", element_id: "elem_value"}}
