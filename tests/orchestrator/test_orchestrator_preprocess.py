from antikythera.models import Blueprint
from antikythera.models import BlueprintSession
from antikythera.models import Task
from antikythera.models import TaskParam
from antikythera_orchestrator.orchestrator import Orchestrator
from antikythera_orchestrator.orchestrator import _create_global_id
from antikythera_orchestrator.sequencers import Sequencer
from antikythera_orchestrator.sequencers import sequencer
from antikythera_orchestrator.storage import BlueprintStorage


def test_preprocess_blueprint_static_composite(mock_immudb, mock_transport_orchestrator):
    """
    Test that _preprocess_blueprint correctly expands static composite tasks
    and populates inner_blueprints and composite_map.
    """
    # 1. Setup Inner Blueprint
    inner_start = Task(id="inner_start", type="system.start")
    inner_task = Task(id="inner_task", type="test.agent")
    inner_end = Task(id="inner_end", type="system.end")
    inner_start >> inner_task >> inner_end
    inner_bp = Blueprint(
        id="inner_bp_id",
        name="Inner Blueprint",
        tasks=[inner_start, inner_task, inner_end],
    )

    # 2. Store Inner Blueprint in Mock Storage
    storage = BlueprintStorage()
    storage.add_blueprint(inner_bp)

    # 3. Setup Outer Blueprint with Composite Task
    outer_start = Task(id="outer_start", type="system.start")
    composite_task = Task(
        id="comp_task",
        type="system.composite",
        params=[TaskParam(name="blueprint", value={"static": "inner_bp_id"})],
    )
    outer_end = Task(id="outer_end", type="system.end")

    outer_start >> composite_task >> outer_end
    outer_bp = Blueprint(
        id="outer_bp_id",
        name="Outer Blueprint",
        tasks=[outer_start, composite_task, outer_end],
    )

    # 4. Setup Session
    session = BlueprintSession(bsid="test_session", blueprint=outer_bp)

    # 5. Initialize Orchestrator which calls _preprocess_blueprint
    orchestrator = Orchestrator(session)

    # 6. Verify inner blueprint loaded into session
    assert "inner_bp_id" in session.inner_blueprints
    assert session.inner_blueprints["inner_bp_id"].id == "inner_bp_id"

    # 7. Verify composite mapping
    fqn = _create_global_id(outer_bp.id, composite_task)
    assert fqn in orchestrator.session.composite_to_inner_blueprint_map
    assert orchestrator.session.composite_to_inner_blueprint_map[fqn] == "inner_bp_id"


def test_preprocess_blueprint_nested_static_composite(mock_immudb, mock_transport_orchestrator):
    """
    Test recursive expansion of nested composite tasks.
    Outer -> Middle -> Deep
    """
    # 1. Setup Blueprints
    deep_start = Task(id="deep_start", type="system.start")
    deep_task = Task(id="deep_task", type="test.agent")
    deep_end = Task(id="deep_end", type="system.end")
    deep_start >> deep_task >> deep_end
    deep_bp = Blueprint(id="deep_bp_id", name="Deep Blueprint", tasks=[deep_start, deep_task, deep_end])

    middle_start = Task(id="middle_start", type="system.start")
    middle_composite = Task(
        id="middle_comp",
        type="system.composite",
        params=[TaskParam(name="blueprint", value={"static": "deep_bp_id"})],
    )
    middle_end = Task(id="middle_end", type="system.end")
    middle_start >> middle_composite >> middle_end
    middle_bp = Blueprint(
        id="middle_bp_id",
        name="Middle Blueprint",
        tasks=[middle_start, middle_composite, middle_end],
    )

    outer_start = Task(id="outer_start", type="system.start")
    outer_composite = Task(
        id="outer_comp",
        type="system.composite",
        params=[TaskParam(name="blueprint", value={"static": "middle_bp_id"})],
    )
    outer_end = Task(id="outer_end", type="system.end")
    outer_start >> outer_composite >> outer_end
    outer_bp = Blueprint(
        id="outer_bp_id",
        name="Outer Blueprint",
        tasks=[outer_start, outer_composite, outer_end],
    )

    # 2. Store Blueprints
    storage = BlueprintStorage()
    storage.add_blueprint(deep_bp)
    storage.add_blueprint(middle_bp)

    # 3. Setup Session
    session = BlueprintSession(bsid="test_nested", blueprint=outer_bp)

    # 4. Init Orchestrator
    orchestrator = Orchestrator(session)

    # 5. Verify all loaded
    assert "middle_bp_id" in session.inner_blueprints
    assert "deep_bp_id" in session.inner_blueprints

    # 6. Verify mappings
    outer_fqn = _create_global_id("outer_bp_id", outer_composite)
    assert outer_fqn in orchestrator.session.composite_to_inner_blueprint_map
    assert orchestrator.session.composite_to_inner_blueprint_map[outer_fqn] == "middle_bp_id"

    middle_fqn = _create_global_id("middle_bp_id", middle_composite)
    assert middle_fqn in orchestrator.session.composite_to_inner_blueprint_map
    assert orchestrator.session.composite_to_inner_blueprint_map[middle_fqn] == "deep_bp_id"


def test_preprocess_dynamic_expansion(mock_immudb, mock_transport_orchestrator):
    """
    Test expansion using a mock sequencer.
    """

    # Register Mock Sequencer
    @sequencer("mock_seq")
    class MockSequencer(Sequencer):
        def expand(self, task: Task, blueprint: Blueprint) -> Blueprint:
            # Replace dynamic task with a static composite task pointing to inner_bp
            # In a real scenario, this would generate tasks.
            # Here we simulate expansion by removing the dynamic task and adding a composite task

            new_composite = Task(
                id="expanded_composite",
                type="system.composite",
                params=[TaskParam(name="blueprint", value={"static": "inner_bp_id"})],
            )

            new_tasks = []
            for t in blueprint.tasks:
                if t.id == task.id:
                    new_tasks.append(new_composite)
                else:
                    new_tasks.append(t)

            # Rebuild connections (simplified for this mock)
            start_node = next(t for t in new_tasks if t.type == "system.start")
            end_node = next(t for t in new_tasks if t.type == "system.end")

            new_composite.depends_on = []
            end_node.depends_on = []

            start_node >> new_composite >> end_node

            blueprint.tasks = new_tasks
            return blueprint

    # Setup Inner Blueprint (target of expansion)
    inner_start = Task(id="inner_start", type="system.start")
    inner_task = Task(id="inner_task", type="test.agent")
    inner_end = Task(id="inner_end", type="system.end")
    inner_start >> inner_task >> inner_end
    inner_bp = Blueprint(
        id="inner_bp_id",
        name="Inner Blueprint",
        tasks=[inner_start, inner_task, inner_end],
    )

    storage = BlueprintStorage()
    storage.add_blueprint(inner_bp)

    # Setup Dynamic Task
    outer_start = Task(id="outer_start", type="system.start")
    dynamic_task = Task(
        id="dyn_task",
        type="system.composite",
        params=[
            TaskParam(
                name="blueprint",
                value={
                    "dynamic": {
                        "sequencer": "mock_seq",
                    }
                },
            )
        ],
    )
    outer_end = Task(id="outer_end", type="system.end")

    outer_start >> dynamic_task >> outer_end
    outer_bp = Blueprint(
        id="outer_bp_id",
        name="Outer Blueprint",
        tasks=[outer_start, dynamic_task, outer_end],
    )

    # Setup Session
    session = BlueprintSession(bsid="test_dynamic", blueprint=outer_bp)

    # Init Orchestrator
    orchestrator = Orchestrator(session)

    # Verify expansion happened
    current_tasks = [t.id for t in session.blueprint.tasks]
    assert "dyn_task" not in current_tasks
    assert "expanded_composite" in current_tasks

    # Verify inner blueprint loaded from the expanded task
    assert "inner_bp_id" in session.inner_blueprints

    # Verify mapping for the NEW composite task
    fqn = None
    for t in session.blueprint.tasks:
        if t.id == "expanded_composite":
            fqn = _create_global_id("outer_bp_id", t)
            break

    assert fqn is not None
    assert fqn in orchestrator.session.composite_to_inner_blueprint_map
    assert orchestrator.session.composite_to_inner_blueprint_map[fqn] == "inner_bp_id"
