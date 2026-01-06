from typing import Any
from typing import Dict

from antikythera.models import Blueprint
from antikythera.models import BlueprintSession
from antikythera.models import BlueprintSessionState
from antikythera.models import Task
from antikythera.models import TaskState
from antikythera_agents.base_agent import Agent
from antikythera_agents.decorators import agent
from antikythera_agents.decorators import tool
from antikythera_agents.launcher import AgentLauncher
from antikythera_orchestrator.orchestrator import Orchestrator


@agent(type="failing_agent")
class FailingAgent(Agent):
    @tool(name="fail_sometimes")
    def fail_sometimes(self, task: Task) -> Dict[str, Any]:
        print(f"Task Inputs: {task.inputs}")
        should_fail = task.inputs.get("should_fail", True)
        if should_fail:
            raise RuntimeError("Planned failure")
        return {"result": "success"}


def test_task_failure_and_retry(mock_immudb, mock_transport_orchestrator, mock_transport_launcher):
    # 1. Define Blueprint
    task_start = Task(id="start", type="system.start")

    # Task that fails initially
    # We pass 'should_fail': True initially (via static input)
    # But later for retry we need to change it?
    # Data comes from session storage.
    # So we map input 'should_fail' to a session variable.

    task = Task(
        id="failable_task",
        type="failing_agent.fail_sometimes",
        inputs={"should_fail": None},
        argument_mapping={"inputs": {"should_fail": "fail_flag"}},
        outputs={"result": "result"},
    )

    task_end = Task(id="end", type="system.end")

    task_start.then(task).then(task_end)

    blueprint = Blueprint(id="fail_bp", name="Failure Blueprint", tasks=[task_start, task, task_end])

    # 2. Session
    session = BlueprintSession(bsid="test_session_fail", blueprint=blueprint)
    orchestrator = Orchestrator(session)

    # Set initial flag to True (Fail)
    orchestrator.session_storage.set(blueprint.id, "fail_flag", True)

    # Verify storage
    assert orchestrator.session_storage.get(blueprint.id, "fail_flag") is True

    # 3. Launcher
    launcher = AgentLauncher()
    launcher.start()

    # 4. Start
    orchestrator.start()

    # 5. Wait for failure
    # await_completion returns True if completed (success OR fail).
    completed = orchestrator.await_completion(timeout=5)
    assert completed

    assert orchestrator.session.state == BlueprintSessionState.FAILED
    assert orchestrator.graph.node[f"{blueprint.id}.{task.id}"]["task"].state == TaskState.FAILED

    # 6. Retry (Resume)
    # First, fix the input so it succeeds this time
    orchestrator.session_storage.set(blueprint.id, "fail_flag", False)

    # Start again
    # This should trigger _reset_failed_tasks
    orchestrator.start()

    # 7. Wait for success
    completed = orchestrator.await_completion(timeout=5)

    if not completed:
        print(f"Session State: {orchestrator.session.state}")
        for node in orchestrator.graph.nodes():
            t = orchestrator.graph.node[node]["task"]
            print(f"Task {t.id} State: {t.state}")

    assert completed

    assert orchestrator.session.state == BlueprintSessionState.COMPLETED
    assert orchestrator.graph.node[f"{blueprint.id}.{task.id}"]["task"].state == TaskState.SUCCEEDED

    result = orchestrator.session_storage.get(blueprint.id, "result")
    assert result == "success"

    orchestrator.stop()
    launcher.stop()
