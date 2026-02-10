from antikythera.models import Blueprint
from antikythera.models import BlueprintSession
from antikythera.models import Task
from antikythera.models import TaskParam
from antikythera.models import TaskState
from antikythera_orchestrator.orchestrator import Orchestrator


def _make_dynamic_composite_task(task_id, inner_blueprint_id, element_id="elem1"):
    """Helper to create a dynamically expanded composite task."""
    return Task(
        id=task_id,
        type="system.composite",
        params=[
            TaskParam(
                name="blueprint",
                value={
                    "dynamic": {
                        "blueprint_id": inner_blueprint_id,
                        "expanded": True,
                        "sequencer": "test",
                        "element": {"element_id": element_id},
                    }
                },
            )
        ],
    )


def _make_trivial_orchestrator(bsid, mock_immudb, mock_transport_orchestrator):
    """Helper to create an orchestrator with a trivial blueprint (no composite preprocessing)."""
    task_start = Task(id="start", type="system.start")
    task_end = Task(id="end", type="system.end")
    task_start >> task_end
    bp = Blueprint(id="trivial", name="Trivial", tasks=[task_start, task_end])
    session = BlueprintSession(bsid=bsid, blueprint=bp)
    return Orchestrator(session)


def test_get_currently_running_composite_blueprints_no_running_tasks(mock_immudb, mock_transport_orchestrator):
    """When no tasks are RUNNING, should return an empty set."""
    orchestrator = _make_trivial_orchestrator("test_no_running", mock_immudb, mock_transport_orchestrator)

    result = orchestrator.get_currently_running_composite_blueprints()

    assert result == set()


def test_get_currently_running_composite_blueprints_ignores_regular_running_task(mock_immudb, mock_transport_orchestrator):
    """A regular (non-dynamic) running task should NOT be included — method is for composite blueprints only."""
    task_start = Task(id="start", type="system.start")
    task_work = Task(id="work", type="system.sleep", params=[TaskParam(name="duration", value=1)])
    task_end = Task(id="end", type="system.end")
    task_start >> task_work >> task_end

    blueprint = Blueprint(id="bp_regular", name="Test", tasks=[task_start, task_work, task_end])
    session = BlueprintSession(bsid="test_regular_ignored", blueprint=blueprint)
    orchestrator = Orchestrator(session)

    orchestrator.graph.node[f"{blueprint.id}.{task_work.id}"]["task"].state = TaskState.RUNNING

    result = orchestrator.get_currently_running_composite_blueprints()

    assert result == set()


def test_get_currently_running_composite_blueprints_with_dynamic_task(mock_immudb, mock_transport_orchestrator):
    """A dynamically expanded running task should return the blueprint_id from its dynamic params."""
    orchestrator = _make_trivial_orchestrator("test_dynamic", mock_immudb, mock_transport_orchestrator)

    task_composite = _make_dynamic_composite_task("dynamic_task", "inner_bp_dynamic")
    task_composite.state = TaskState.RUNNING
    orchestrator.graph.add_node("outer_bp.dynamic_task", task=task_composite, blueprint_id="outer_bp")

    result = orchestrator.get_currently_running_composite_blueprints()

    assert result == {"inner_bp_dynamic"}


def test_get_currently_running_composite_blueprints_multiple_dynamic_tasks(mock_immudb, mock_transport_orchestrator):
    """Multiple running dynamic tasks with different inner blueprints should all be returned."""
    orchestrator = _make_trivial_orchestrator("test_multi_dynamic", mock_immudb, mock_transport_orchestrator)

    task_a = _make_dynamic_composite_task("dyn_a", "inner_bp_a", element_id="elem_a")
    task_a.state = TaskState.RUNNING
    orchestrator.graph.add_node("bp.dyn_a", task=task_a, blueprint_id="bp")

    task_b = _make_dynamic_composite_task("dyn_b", "inner_bp_b", element_id="elem_b")
    task_b.state = TaskState.RUNNING
    orchestrator.graph.add_node("bp.dyn_b", task=task_b, blueprint_id="bp")

    result = orchestrator.get_currently_running_composite_blueprints()

    assert result == {"inner_bp_a", "inner_bp_b"}


def test_get_currently_running_composite_blueprints_ignores_non_running_dynamic(mock_immudb, mock_transport_orchestrator):
    """Dynamic composite tasks not in RUNNING state should not be included."""
    orchestrator = _make_trivial_orchestrator("test_non_running_dynamic", mock_immudb, mock_transport_orchestrator)

    task_succeeded = _make_dynamic_composite_task("dyn_done", "inner_bp_done")
    task_succeeded.state = TaskState.SUCCEEDED
    orchestrator.graph.add_node("bp.dyn_done", task=task_succeeded, blueprint_id="bp")

    task_pending = _make_dynamic_composite_task("dyn_pending", "inner_bp_pending")
    task_pending.state = TaskState.PENDING
    orchestrator.graph.add_node("bp.dyn_pending", task=task_pending, blueprint_id="bp")

    result = orchestrator.get_currently_running_composite_blueprints()

    assert result == set()
