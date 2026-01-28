from typing import Any
from typing import Dict

from antikythera.models import Blueprint
from antikythera.models import BlueprintSession
from antikythera.models import Task
from antikythera.models import TaskInput
from antikythera.models import TaskOutput
from antikythera.models import TaskState
from antikythera_agents.base_agent import Agent
from antikythera_agents.decorators import agent
from antikythera_agents.decorators import tool
from antikythera_agents.launcher import AgentLauncher
from antikythera_orchestrator.orchestrator import Orchestrator


# Define a test agent
# We use a unique type to avoid conflicts
@agent(type="test_data_agent")
class TestDataAgent(Agent):
    @tool(name="producer")
    def producer(self, task: Task) -> Dict[str, Any]:
        return {"value": 42}

    @tool(name="consumer")
    def consumer(self, task: Task) -> Dict[str, Any]:
        input_val = task.get_input_value("input_value")
        # We return what we received to verify it in the test
        return {"received": input_val}

    @tool(name="static_consumer")
    def static_consumer(self, task: Task) -> Dict[str, Any]:
        static_val = task.get_input_value("static_val")
        return {"received": static_val}


def test_data_passing_between_tasks(mock_immudb, mock_transport_orchestrator, mock_transport_launcher):
    # 1. Define blueprint
    task_start = Task(id="start", type="system.start")

    # Task A: Produces {"value": 42}
    # We want output 'value' to be stored as 'value' in session (default behavior)
    task_a = Task(
        id="task_a",
        type="test_data_agent.producer",
        outputs=[TaskOutput(name="value")],
    )

    # Task B: Consumes "value" as "input_value"
    # We need to map session key 'value' to task input 'input_value'
    task_b = Task(
        id="task_b",
        type="test_data_agent.consumer",
        inputs=[TaskInput(name="input_value", get_from="value")],
        outputs=[TaskOutput(name="received")],
    )

    task_end = Task(id="end", type="system.end")

    task_start >> task_a >> task_b >> task_end

    blueprint = Blueprint(id="data_flow_bp", name="Data Flow Blueprint", tasks=[task_start, task_a, task_b, task_end])

    # 2. Session & Orchestrator
    session = BlueprintSession(bsid="test_session_data_flow", blueprint=blueprint)
    orchestrator = Orchestrator(session)

    # 3. Launcher
    launcher = AgentLauncher()
    launcher.start()

    # 4. Start
    orchestrator.start()

    # 5. Wait
    completed = orchestrator.await_completion(timeout=5)

    # Debug info
    print(f"Session State: {orchestrator.session.state}")
    for node in orchestrator.graph.nodes():
        task = orchestrator.graph.node[node]["task"]
        print(f"Task {task.id} State: {task.state}")
        if task.state == TaskState.FAILED:
            print(f"Task {task.id} failed.")

    assert completed

    # 6. Verify
    # Check session storage for intermediate and final values
    val_a = orchestrator.session_storage.get(blueprint.id, "value")
    assert val_a == 42

    val_b = orchestrator.session_storage.get(blueprint.id, "received")
    assert val_b == 42

    orchestrator.stop()
    launcher.stop()


def test_static_inputs(mock_immudb, mock_transport_orchestrator, mock_transport_launcher):
    # 1. Define blueprint
    task_start = Task(id="start", type="system.start")

    # Task with static input
    task_static = Task(
        id="task_static",
        type="test_data_agent.static_consumer",
        inputs=[TaskInput(name="static_val", value=123)],  # Static integer
        outputs=[TaskOutput(name="received", set_to="received_static")],
    )

    task_end = Task(id="end", type="system.end")

    task_start >> task_static >> task_end

    blueprint = Blueprint(id="static_input_bp", name="Static Input Blueprint", tasks=[task_start, task_static, task_end])

    session = BlueprintSession(bsid="test_session_static", blueprint=blueprint)
    orchestrator = Orchestrator(session)

    launcher = AgentLauncher()
    launcher.start()

    orchestrator.start()

    completed = orchestrator.await_completion(timeout=5)
    assert completed

    val = orchestrator.session_storage.get(blueprint.id, "received_static")
    assert val == 123

    orchestrator.stop()
    launcher.stop()
