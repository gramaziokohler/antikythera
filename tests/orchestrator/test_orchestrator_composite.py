from typing import Any
from typing import Dict

from antikythera.models import Blueprint
from antikythera.models import BlueprintSession
from antikythera.models import Task
from antikythera.models import TaskInput
from antikythera.models import TaskOutput
from antikythera.models import TaskParam
from antikythera.models import TaskState
from antikythera_agents.base_agent import Agent
from antikythera_agents.decorators import agent
from antikythera_agents.decorators import tool
from antikythera_agents.launcher import AgentLauncher
from antikythera_orchestrator.orchestrator import Orchestrator
from antikythera_orchestrator.storage import BlueprintStorage


def test_composite_task_execution(mock_immudb, mock_transport_orchestrator, mock_transport_launcher):
    # 1. Define Inner Blueprint
    # Inner Task: Multiplies input by 2
    # We'll use a custom agent or reuse TestDataAgent if I can import it or redefine it.
    # Since TestDataAgent is in test_orchestrator_data_flow.py, I can't easily import it if it's not in a module.
    # I'll define a simple agent here as well or move TestDataAgent to conftest or a shared file.
    # For simplicity, I'll redefine a similar agent here with a different type name.

    @agent(type="composite_test_agent")
    class CompositeTestAgent(Agent):
        @tool(name="multiplier")
        def multiplier(self, task: Task) -> Dict[str, Any]:
            val = task.get_input_value("val")
            return {"result": val * 2}

    # Inner Blueprint tasks
    inner_start = Task(id="inner_start", type="system.start")

    inner_task = Task(
        id="inner_task",
        type="composite_test_agent.multiplier",
        inputs=[TaskInput(name="val", get_from="inner_input")],
        outputs=[TaskOutput(name="result")],
    )

    inner_end = Task(id="inner_end", type="system.end")

    inner_start >> inner_task >> inner_end

    inner_blueprint = Blueprint(
        id="inner_bp",
        name="Inner Blueprint",
        tasks=[inner_start, inner_task, inner_end],
    )

    # 2. Store Inner Blueprint
    # We need to store it so Orchestrator can find it by ID
    storage = BlueprintStorage()
    storage.add_blueprint(inner_blueprint)

    # 3. Define Outer Blueprint
    # Task 1: Produce value 10
    task_start_sys = Task(id="sys_start", type="system.start")

    task_start = Task(
        id="start",
        type="composite_test_agent.multiplier",
        inputs=[TaskInput(name="val", value=5)],  # Static input 5
        outputs=[TaskOutput(name="result")],  # Output 'result' = 10. Mapped to session key 'result'
    )

    # Task 2: Composite Task
    # Input: 'inner_input' (for inner blueprint) <- 'result' (from task_start)
    # Output: 'final_result' (from inner blueprint) <- 'result' (from inner task)

    # Note: Composite task inputs are mapped to inner session storage.
    # Composite task outputs are mapped from inner session storage to outer session storage.

    task_composite = Task(
        id="composite",
        type="system.composite",
        params=[TaskParam(name="blueprint", value={"static": "inner_bp"})],
        inputs=[TaskInput(name="inner_input", get_from="result")],  # Map outer 'result' to inner 'inner_input'
        outputs=[TaskOutput(name="result", set_to="final_result")],  # Map inner 'result' to outer 'final_result'
    )

    task_end_sys = Task(id="sys_end", type="system.end")

    task_start_sys >> task_start >> task_composite >> task_end_sys

    outer_blueprint = Blueprint(id="outer_bp", name="Outer Blueprint", tasks=[task_start_sys, task_start, task_composite, task_end_sys])

    # 4. Session & Orchestrator
    session = BlueprintSession(bsid="test_session_composite", blueprint=outer_blueprint)
    orchestrator = Orchestrator(session)

    # 5. Launcher
    launcher = AgentLauncher()
    launcher.start()

    # 6. Start
    orchestrator.start()

    # 7. Wait
    completed = orchestrator.await_completion(timeout=5)

    # Debug info
    print(f"Session State: {orchestrator.session.state}")
    for node in orchestrator.graph.nodes():
        task = orchestrator.graph.node[node]["task"]
        print(f"Task {task.id} State: {task.state}")
        if task.state == TaskState.FAILED:
            print(f"Task {task.id} failed.")

    assert completed

    # 8. Verify
    # Outer session should have 'final_result' = 20 (5 * 2 * 2? No, start: 5*2=10. Inner: 10*2=20)
    final_val = orchestrator.session_storage.get(outer_blueprint.id, "final_result")
    assert final_val == 20

    orchestrator.stop()
    launcher.stop()
