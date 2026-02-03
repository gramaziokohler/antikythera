from antikythera.models import Blueprint
from antikythera.models import BlueprintSession
from antikythera.models import BlueprintSessionState
from antikythera.models import Task
from antikythera.models import TaskParam
from antikythera_agents.launcher import AgentLauncher
from antikythera_orchestrator.orchestrator import Orchestrator


def test_start_simple_session(mock_immudb, mock_transport_orchestrator, mock_transport_launcher):
    # 1. Define a simple blueprint
    task_start = Task(id="start", type="system.start")
    task_sleep = Task(id="sleep_task", type="system.sleep", params=[TaskParam(name="duration", value=0.1)])
    task_end = Task(id="end", type="system.end")

    # Chain tasks: start -> sleep -> end
    task_start >> task_sleep >> task_end

    blueprint = Blueprint(id="simple_bp", name="Simple Blueprint", tasks=[task_start, task_sleep, task_end])

    # 2. Create a session
    session = BlueprintSession(bsid="test_session_1", blueprint=blueprint)

    # 3. Instantiate Orchestrator
    # This will trigger storage initialization which uses our mock_immudb
    orchestrator = Orchestrator(session)

    # 4. Instantiate and start Agent Launcher
    launcher = AgentLauncher()
    launcher.start()

    # 5. Start the session
    orchestrator.start()

    # 6. Verify state
    assert orchestrator.session.state == BlueprintSessionState.RUNNING

    # Verify storage was used
    loaded_session = orchestrator.session_storage.load_session()
    assert loaded_session is not None
    assert loaded_session.state == BlueprintSessionState.RUNNING
    assert loaded_session.blueprint.id == "simple_bp"

    # Wait for tasks to complete
    orchestrator.await_completion(timeout=10)

    # Clean up
    orchestrator.stop()
    launcher.stop()
