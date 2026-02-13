from antikythera.models import Blueprint
from antikythera.models import BlueprintSession
from antikythera.models import Task
from antikythera.models import TaskParam
from antikythera.models import TaskState
from antikythera_orchestrator.orchestrator import Orchestrator
from antikythera_orchestrator.orchestrator import _create_global_id


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


# ===========================================================================
# Tests for _handle_skipped_task / _set_inner_blueprint_tasks_state
# ===========================================================================


def test_handle_skipped_composite_task_skips_inner_blueprint_tasks(mock_immudb, mock_transport_orchestrator):
    """When a composite task is skipped, all tasks in its inner blueprint should also be marked SKIPPED."""
    orchestrator = _make_trivial_orchestrator("test_skip_inner", mock_immudb, mock_transport_orchestrator)

    outer_bp_id = "outer_bp"
    inner_bp_id = "inner_bp_skip"

    # Create the composite task on the outer blueprint
    composite_task = _make_dynamic_composite_task("comp_skip", inner_bp_id)
    fqn_composite_id = f"{outer_bp_id}.{composite_task.id}"
    orchestrator.graph.add_node(fqn_composite_id, task=composite_task, blueprint_id=outer_bp_id)

    # Create inner blueprint tasks
    inner_start = Task(id="start", type="system.start")
    inner_work = Task(id="work", type="some.task")
    inner_end = Task(id="end", type="system.end")
    for inner_task in [inner_start, inner_work, inner_end]:
        fqn_id = _create_global_id(inner_bp_id, inner_task)
        orchestrator.graph.add_node(fqn_id, task=inner_task, blueprint_id=inner_bp_id)

    # Register the composite-to-inner mapping
    orchestrator.session.composite_to_inner_blueprint_map[fqn_composite_id] = inner_bp_id

    # Skip the composite task
    orchestrator._handle_skipped_task(composite_task, outer_bp_id)

    # All inner blueprint tasks should now be SKIPPED
    assert inner_start.state == TaskState.SKIPPED
    assert inner_work.state == TaskState.SKIPPED
    assert inner_end.state == TaskState.SKIPPED
    assert composite_task.state == TaskState.SKIPPED


def test_skip_inner_blueprint_preserves_already_terminal_tasks(mock_immudb, mock_transport_orchestrator):
    """Tasks already in a terminal state (SUCCEEDED, FAILED) should not be changed when skipping."""
    orchestrator = _make_trivial_orchestrator("test_skip_preserve", mock_immudb, mock_transport_orchestrator)

    inner_bp_id = "inner_bp_preserve"

    task_succeeded = Task(id="done", type="some.task", state=TaskState.SUCCEEDED)
    task_failed = Task(id="broken", type="some.task", state=TaskState.FAILED)
    task_pending = Task(id="waiting", type="some.task", state=TaskState.PENDING)

    for t in [task_succeeded, task_failed, task_pending]:
        orchestrator.graph.add_node(_create_global_id(inner_bp_id, t), task=t, blueprint_id=inner_bp_id)

    orchestrator._set_inner_blueprint_tasks_state(inner_bp_id, TaskState.SKIPPED)

    assert task_succeeded.state == TaskState.SUCCEEDED
    assert task_failed.state == TaskState.FAILED
    assert task_pending.state == TaskState.SKIPPED


def test_skip_inner_blueprint_does_not_affect_other_blueprints(mock_immudb, mock_transport_orchestrator):
    """Skipping inner blueprint tasks should not affect tasks from other blueprints."""
    orchestrator = _make_trivial_orchestrator("test_skip_isolation", mock_immudb, mock_transport_orchestrator)

    target_bp_id = "target_bp"
    other_bp_id = "other_bp"

    target_task = Task(id="t1", type="some.task")
    other_task = Task(id="t2", type="some.task")

    orchestrator.graph.add_node(_create_global_id(target_bp_id, target_task), task=target_task, blueprint_id=target_bp_id)
    orchestrator.graph.add_node(_create_global_id(other_bp_id, other_task), task=other_task, blueprint_id=other_bp_id)

    orchestrator._set_inner_blueprint_tasks_state(target_bp_id, TaskState.SKIPPED)

    assert target_task.state == TaskState.SKIPPED
    assert other_task.state == TaskState.PENDING


def test_skip_inner_blueprint_recursively_skips_nested_composites(mock_immudb, mock_transport_orchestrator):
    """If an inner blueprint contains composite tasks, their inner blueprints should also be skipped recursively."""
    orchestrator = _make_trivial_orchestrator("test_skip_recursive", mock_immudb, mock_transport_orchestrator)

    # outer_bp_id = "outer_bp"
    inner_bp_id = "inner_bp"
    nested_bp_id = "nested_bp"

    # Inner blueprint has a composite task that expands to a nested blueprint
    inner_start = Task(id="start", type="system.start")
    inner_composite = _make_dynamic_composite_task("nested_comp", nested_bp_id)
    inner_end = Task(id="end", type="system.end")
    for t in [inner_start, inner_composite, inner_end]:
        orchestrator.graph.add_node(_create_global_id(inner_bp_id, t), task=t, blueprint_id=inner_bp_id)

    # Register the inner composite -> nested blueprint mapping
    fqn_inner_composite = _create_global_id(inner_bp_id, inner_composite)
    orchestrator.session.composite_to_inner_blueprint_map[fqn_inner_composite] = nested_bp_id

    # Nested blueprint has its own tasks
    nested_start = Task(id="start", type="system.start")
    nested_work = Task(id="work", type="some.task")
    nested_end = Task(id="end", type="system.end")
    for t in [nested_start, nested_work, nested_end]:
        orchestrator.graph.add_node(_create_global_id(nested_bp_id, t), task=t, blueprint_id=nested_bp_id)

    # Skip the inner blueprint
    orchestrator._set_inner_blueprint_tasks_state(inner_bp_id, TaskState.SKIPPED)

    # Inner blueprint tasks should be skipped
    assert inner_start.state == TaskState.SKIPPED
    assert inner_composite.state == TaskState.SKIPPED
    assert inner_end.state == TaskState.SKIPPED

    # Nested blueprint tasks should also be skipped
    assert nested_start.state == TaskState.SKIPPED
    assert nested_work.state == TaskState.SKIPPED
    assert nested_end.state == TaskState.SKIPPED


# ===========================================================================
# Tests for _reset_failed_tasks (session resume)
# ===========================================================================


def test_reset_failed_tasks_resets_running_and_ready_tasks(mock_immudb, mock_transport_orchestrator):
    """On resume, RUNNING and READY tasks should be reset to PENDING alongside FAILED tasks."""
    task_start = Task(id="start", type="system.start")
    task_a = Task(id="a", type="some.task")
    task_b = Task(id="b", type="some.task")
    task_c = Task(id="c", type="some.task")
    task_end = Task(id="end", type="system.end")
    task_start >> task_a >> task_b >> task_c >> task_end

    blueprint = Blueprint(id="bp_reset", name="Test", tasks=[task_start, task_a, task_b, task_c, task_end])
    session = BlueprintSession(bsid="test_reset_states", blueprint=blueprint)
    orchestrator = Orchestrator(session)

    # Simulate a stopped session with tasks in various states
    orchestrator.graph.node[f"{blueprint.id}.{task_start.id}"]["task"].state = TaskState.SUCCEEDED
    orchestrator.graph.node[f"{blueprint.id}.{task_a.id}"]["task"].state = TaskState.FAILED
    orchestrator.graph.node[f"{blueprint.id}.{task_b.id}"]["task"].state = TaskState.RUNNING
    orchestrator.graph.node[f"{blueprint.id}.{task_c.id}"]["task"].state = TaskState.READY

    orchestrator._reset_failed_tasks()

    assert task_start.state == TaskState.SUCCEEDED  # should stay
    assert task_a.state == TaskState.PENDING  # FAILED -> PENDING
    assert task_b.state == TaskState.PENDING  # RUNNING -> PENDING
    assert task_c.state == TaskState.PENDING  # READY -> PENDING
    assert task_end.state == TaskState.PENDING  # was already PENDING


# ===========================================================================
# Tests for skip_task_state
# ===========================================================================


def test_skip_task_state_skips_single_task(mock_immudb, mock_transport_orchestrator):
    """skip_task_state should only skip the target task, not downstream dependents."""
    task_start = Task(id="start", type="system.start")
    task_a = Task(id="a", type="some.task")
    task_b = Task(id="b", type="some.task")
    task_end = Task(id="end", type="system.end")
    task_start >> task_a >> task_b >> task_end

    blueprint = Blueprint(id="bp_skip", name="Test", tasks=[task_start, task_a, task_b, task_end])
    session = BlueprintSession(bsid="test_skip_single", blueprint=blueprint)
    orchestrator = Orchestrator(session)

    result = orchestrator.skip_task_state("bp_skip", "a")

    assert "bp_skip.a" in result
    assert task_a.state == TaskState.SKIP_REQUESTED
    assert task_b.state == TaskState.PENDING  # downstream NOT affected
    assert task_end.state == TaskState.PENDING  # downstream NOT affected


def test_skip_task_state_skips_composite_inner_blueprints(mock_immudb, mock_transport_orchestrator):
    """Skipping a composite task should also recursively skip its inner blueprint tasks."""
    orchestrator = _make_trivial_orchestrator("test_skip_composite_api", mock_immudb, mock_transport_orchestrator)

    outer_bp_id = "outer"
    inner_bp_id = "inner_bp"

    # Add a composite task to the graph
    composite_task = _make_dynamic_composite_task("comp", inner_bp_id)
    fqn_composite = _create_global_id(outer_bp_id, composite_task)
    orchestrator.graph.add_node(fqn_composite, task=composite_task, blueprint_id=outer_bp_id)

    # Add inner blueprint tasks
    inner_start = Task(id="start", type="system.start")
    inner_work = Task(id="work", type="some.task")
    inner_end = Task(id="end", type="system.end")
    for t in [inner_start, inner_work, inner_end]:
        orchestrator.graph.add_node(_create_global_id(inner_bp_id, t), task=t, blueprint_id=inner_bp_id)

    # Register the mapping
    orchestrator.session.composite_to_inner_blueprint_map[fqn_composite] = inner_bp_id

    orchestrator.skip_task_state(outer_bp_id, "comp")

    assert composite_task.state == TaskState.SKIP_REQUESTED
    assert inner_start.state == TaskState.SKIP_REQUESTED
    assert inner_work.state == TaskState.SKIP_REQUESTED
    assert inner_end.state == TaskState.SKIP_REQUESTED


def test_skip_task_state_raises_on_unknown_task(mock_immudb, mock_transport_orchestrator):
    """skip_task_state should raise KeyError for a non-existent task."""
    orchestrator = _make_trivial_orchestrator("test_skip_unknown", mock_immudb, mock_transport_orchestrator)

    try:
        orchestrator.skip_task_state("trivial", "nonexistent")
        assert False, "Expected KeyError"
    except KeyError:
        pass


def test_task_scheduler_skipped(mock_immudb, mock_transport_orchestrator, mock_transport_launcher):
    # 1. Define a simple blueprint with multiple tasks and dependencies
    task_start = Task(id="start", type="system.start")
    task_1 = Task(id="task_1", type="system.sleep", params=[TaskParam(name="duration", value=1.0)])
    task_2 = Task(id="task_2", type="system.sleep", params=[TaskParam(name="duration", value=1.0)])
    task_3 = Task(id="task_3", type="system.sleep", params=[TaskParam(name="duration", value=1.0)])
    task_4 = Task(id="task_4", type="system.sleep", params=[TaskParam(name="duration", value=1.0)])

    task_end = Task(id="end", type="system.end")

    task_start >> task_1 >> task_2 >> task_3 >> task_4 >> task_end

    blueprint = Blueprint(id="test_bp_id", name="Test Blueprint", tasks=[task_start, task_1, task_2, task_3, task_4, task_end])
    session = BlueprintSession(bsid="test_session_id", blueprint=blueprint)
    orchestrator = Orchestrator(session)

    task_start.state = TaskState.SUCCEEDED
    task_2.state = TaskState.SKIP_REQUESTED
    pending_tasks = orchestrator.scheduler.get_pending_tasks()

    assert len(pending_tasks) == 1
    assert pending_tasks[0].task.id == "task_1"

    task_1.state = TaskState.SUCCEEDED
    pending_tasks = orchestrator.scheduler.get_pending_tasks()
    assert len(pending_tasks) == 1
    assert pending_tasks[0].task.id == "task_2"

    task_2.state = TaskState.SKIPPED
    pending_tasks = orchestrator.scheduler.get_pending_tasks()
    assert len(pending_tasks) == 1
    assert pending_tasks[0].task.id == "task_3"
