import threading
import time
from typing import Any
from typing import Dict

from compas_model.elements import Element
from compas_model.models import Model  # Verify import if possible

from antikythera.models import Blueprint
from antikythera.models import BlueprintSession
from antikythera.models import Task
from antikythera.models import TaskInput
from antikythera.models import TaskOutput
from antikythera.models import TaskParam
from antikythera.models.blueprints import BlueprintSessionState
from antikythera_agents.base_agent import Agent
from antikythera_agents.decorators import agent
from antikythera_agents.decorators import tool
from antikythera_agents.launcher import AgentLauncher
from antikythera_orchestrator.orchestrator import Orchestrator
from antikythera_orchestrator.storage import BlueprintStorage
from antikythera_orchestrator.storage import ModelStorage
from antikythera_orchestrator.storage import SessionStorage


@agent(type="test_dynamic")
class DynamicExpansionTestAgent(Agent):
    @tool(name="process")
    def process_element(self, task: Task) -> Dict[str, Any]:
        guid = task.context.get("element_id")
        assert guid is not None
        print(f"#### Processing element with GUID: {guid}")
        return {"processed": True}


def test_dynamic_expansion_basic_sequencer(mock_immudb, mock_transport_orchestrator, mock_transport_launcher, fast_system_agents, cleanup_manager):
    model = Model()
    element1 = Element()
    element2 = Element()
    model.add_element(element1)
    model.add_element(element2)

    model_id = "test_model_01"

    with ModelStorage() as storage:
        storage.add_model(model_id, model)

    inner_start = Task(id="inner_start", type="system.start")

    inner_process = Task(id="mark_processed", type="test_dynamic.process", outputs=[TaskOutput(name="processed")])

    inner_end = Task(id="inner_end", type="system.end")

    inner_start >> inner_process >> inner_end

    inner_blueprint = Blueprint(id="test_inner_bp", name="Test Inner Blueprint", tasks=[inner_start, inner_process, inner_end])

    with BlueprintStorage() as bp_storage:
        bp_storage.add_blueprint(inner_blueprint)

    outer_start = Task(id="start", type="system.start")

    dynamic_task = Task(
        id="dynamic_process",
        type="system.composite",
        params=[
            TaskParam(name="blueprint", value={"dynamic": {"blueprint_id": "test_inner_bp", "sequencer": "basic_sequencer"}}),
        ],
    )

    assert dynamic_task.is_dynamic

    outer_end = Task(id="end", type="system.end")

    outer_start >> dynamic_task >> outer_end

    """
    Before expansion

    test_outer_bp
    ├── start (system.start)
    ├── dynamic_process (system.composite)
           (test_inner_bp)
    ├───── inner_start (system.start)
    ├───── mark_processed (test_dynamic.process)
    ├───── inner_end (system.end)
    └── end (system.end)

    """
    """
    After expansion

    test_outer_bp
    ├── start (system.start)
    ├── dynamic_process_0 (system.composite)
          (test_inner_bp_xxx)
    ├───── inner_start (system.start)
    ├───── mark_processed (test_dynamic.process)
    ├───── inner_end (system.end)
    ├── dynamic_process_1 (system.composite)
          (test_inner_bp_xxx)
    ├───── inner_start (system.start)
    ├───── mark_processed (test_dynamic.process)
    ├───── inner_end (system.end)
    └── end (system.end)

    """

    outer_blueprint = Blueprint(id="test_outer_bp", name="Test Outer Dynamic Blueprint", tasks=[outer_start, dynamic_task, outer_end])

    session = BlueprintSession(
        bsid="test_session_dynamic",
        blueprint=outer_blueprint,
        params={"model_id": model_id},  # Important: pass model_id
    )

    orchestrator = cleanup_manager.register(Orchestrator(session))

    launcher = cleanup_manager.register(AgentLauncher())
    launcher.agents["test_dynamic"] = DynamicExpansionTestAgent()
    launcher.start()

    orchestrator.start()

    assert orchestrator.await_completion(timeout=10)

    graph_tasks = [data["task"] for _, data in orchestrator.graph.nodes(data=True)]
    task_ids = [t.id for t in graph_tasks]

    assert "dynamic_process_0" in task_ids
    assert "dynamic_process_1" in task_ids
    assert "dynamic_process" not in task_ids  # Original task should be gone/replaced

    task_0 = next(t for t in graph_tasks if t.id == "dynamic_process_0")
    task_1 = next(t for t in graph_tasks if t.id == "dynamic_process_1")

    task_0_element_id = task_0.get_param_value("blueprint")["dynamic"]["element"]["element_id"]
    task_1_element_id = task_1.get_param_value("blueprint")["dynamic"]["element"]["element_id"]
    assert task_0_element_id == str(element1.guid)
    assert task_1_element_id == str(element2.guid)

    subtasks = [t for t in graph_tasks if t.id == "mark_processed"]
    for subtask in subtasks:
        assert subtask.get_output_value("processed")

    assert session.state == BlueprintSessionState.COMPLETED


def test_dynamic_expansion_pause_resume(mock_immudb, mock_transport_orchestrator, mock_transport_launcher, fast_system_agents, cleanup_manager):
    # Setup
    model = Model()
    element1 = Element()
    element2 = Element()
    model.add_element(element1)
    model.add_element(element2)

    model_id = "test_model_pause_resume"

    with ModelStorage() as storage:
        storage.add_model(model_id, model)

    # Inner blueprint
    inner_start = Task(id="inner_start", type="system.start")
    inner_process = Task(
        id="process",
        type="test_dynamic.process",
        inputs=[TaskInput(name="element")],
    )
    inner_end = Task(id="inner_end", type="system.end")
    inner_start >> inner_process >> inner_end
    inner_blueprint = Blueprint(id="test_inner_bp_pr", name="Test Inner Blueprint PR", tasks=[inner_start, inner_process, inner_end])

    with BlueprintStorage() as bp_storage:
        bp_storage.add_blueprint(inner_blueprint)

    # Outer blueprint
    outer_start = Task(id="start", type="system.start")
    dynamic_task = Task(
        id="dynamic_process",
        type="system.composite",
        params=[
            TaskParam(name="blueprint", value={"dynamic": {"blueprint_id": "test_inner_bp_pr", "sequencer": "basic_sequencer"}}),
        ],
    )
    outer_end = Task(id="end", type="system.end")
    outer_start >> dynamic_task >> outer_end
    outer_blueprint = Blueprint(id="test_outer_bp_pr", name="Test Outer Dynamic Blueprint PR", tasks=[outer_start, dynamic_task, outer_end])

    session = BlueprintSession(
        bsid="test_session_pause_resume",
        blueprint=outer_blueprint,
        params={"model_id": model_id},
    )

    orchestrator = cleanup_manager.register(Orchestrator(session))

    launcher = cleanup_manager.register(AgentLauncher())

    blocking_event = threading.Event()

    class BlockingTestAgent(Agent):
        @tool(name="process")
        def process_element(self, task: Task) -> Dict[str, Any]:
            # Wait for event
            blocking_event.wait(timeout=5)
            return {"processed": True}

    launcher.agents["test_dynamic"] = BlockingTestAgent()
    launcher.start()

    # Test starts!
    orchestrator.start()

    time.sleep(1.0)

    assert orchestrator.state == BlueprintSessionState.RUNNING

    orchestrator.pause()
    assert orchestrator.state == BlueprintSessionState.STOPPED

    blocking_event.set()

    time.sleep(1.0)

    assert orchestrator.state == BlueprintSessionState.STOPPED

    orchestrator.start()

    assert orchestrator.await_completion(timeout=10)
    assert session.state == BlueprintSessionState.COMPLETED


def _get_bp_session_from_storage(session_id: str) -> BlueprintSession:
    with SessionStorage(session_id) as session_storage:
        return session_storage.load_session()


def test_dynamic_expansion_pause_resume_dead_session(mock_immudb, mock_transport_orchestrator, mock_transport_launcher, fast_system_agents, cleanup_manager):
    # 1. Setup Model (Same as basic test)
    model = Model()
    element1 = Element(name="Element 1")
    element2 = Element(name="Element 2")
    element3 = Element(name="Element 3")
    model.add_element(element1)
    model.add_element(element2)
    model.add_element(element3)

    model_id = "test_model_pause_resume"

    with ModelStorage() as storage:
        storage.add_model(model_id, model)

    # 2. Setup Inner Blueprint
    inner_start = Task(id="start", type="system.start")
    inner_process = Task(
        id="process",
        type="test_dynamic.process",
        inputs=[TaskInput(name="element")],
    )
    inner_end = Task(id="end", type="system.end")
    inner_start >> inner_process >> inner_end
    inner_blueprint = Blueprint(id="test_inner_bp_pr", name="Test Inner Blueprint PR", tasks=[inner_start, inner_process, inner_end])

    with BlueprintStorage() as bp_storage:
        bp_storage.add_blueprint(inner_blueprint)

    # 3. Setup Outer Blueprint (Dynamic)
    outer_start = Task(id="start", type="system.start")
    dynamic_task = Task(
        id="dynamic_process",
        type="system.composite",
        params=[TaskParam(name="blueprint", value={"dynamic": {"blueprint_id": "test_inner_bp_pr", "sequencer": "basic_sequencer"}})],
    )
    outer_end = Task(id="end", type="system.end")
    outer_start >> dynamic_task >> outer_end
    outer_blueprint = Blueprint(id="test_outer_bp_pr", name="Test Outer Dynamic Blueprint PR", tasks=[outer_start, dynamic_task, outer_end])

    # 4. Initialize Session
    session = BlueprintSession(
        bsid="test_session_pause_resume_ds",
        blueprint=outer_blueprint,
        params={"model_id": model_id},
    )

    orchestrator = cleanup_manager.register(Orchestrator(session))
    original_map = dict(orchestrator.session.composite_to_inner_blueprint_map)
    # The map will contain the expanded tasks, not the original dynamic_process task
    # assert orchestrator.session.composite_to_inner_blueprint_map == {"test_outer_bp_pr.dynamic_process": "test_inner_bp_pr"}

    # 5. Start Execution with Blocking Agent
    launcher = cleanup_manager.register(AgentLauncher())

    blocking_event = threading.Event()

    class BlockingTestAgent(Agent):
        @tool(name="process")
        def process_element(self, task: Task) -> Dict[str, Any]:
            # Wait for event
            model = task.get_param_value("model")
            element_guid = task.context["element_id"]
            element = model._elements[element_guid]
            if element.name == "Element 2":
                blocking_event.wait(timeout=5)
            return {"processed": True}

    # Register our test agent
    launcher.agents["test_dynamic"] = BlockingTestAgent()
    launcher.start()

    orchestrator.start()

    # Allow some time for the first task to start and block
    time.sleep(1.0)

    assert orchestrator.state == BlueprintSessionState.RUNNING

    orchestrator.pause()

    blocking_event.set()
    time.sleep(1.0)

    orchestrator.stop()
    assert orchestrator.state == BlueprintSessionState.STOPPED

    del orchestrator
    del session

    session = _get_bp_session_from_storage("test_session_pause_resume_ds")
    orchestrator = cleanup_manager.register(Orchestrator(session))

    assert orchestrator.session.composite_to_inner_blueprint_map == original_map

    orchestrator.start()

    assert orchestrator.await_completion(timeout=10)
    assert orchestrator.session.state == BlueprintSessionState.COMPLETED
