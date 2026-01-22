import time

from antikythera.models import Blueprint
from antikythera.models import BlueprintSession
from antikythera.models import BlueprintSessionState
from antikythera.models import Task
from antikythera.models import TaskState
from antikythera_agents.launcher import AgentLauncher
from antikythera_orchestrator.orchestrator import Orchestrator
from antikythera_orchestrator.orchestrator import OrchestratorState


def test_orchestrator_pause_resume(mock_immudb, mock_transport_orchestrator, mock_transport_launcher):
    # 1. Define a blueprint with two sequential tasks
    task_start = Task(id="start", type="system.start")

    # Task 1: Sleep for a bit to give us time to pause
    task_1 = Task(id="task_1", type="system.sleep", params={"duration": 0.5})
    # Task 2: Another sleep
    task_2 = Task(id="task_2", type="system.sleep", params={"duration": 0.1})

    task_end = Task(id="end", type="system.end")

    task_start >> task_1 >> task_2 >> task_end

    blueprint = Blueprint(id="pause_resume_bp", name="Pause Resume Blueprint", tasks=[task_start, task_1, task_2, task_end])

    # 2. Create a session
    bsid = "test_session_pause_resume"
    session = BlueprintSession(bsid=bsid, blueprint=blueprint)

    # 3. Instantiate Orchestrator
    orchestrator = Orchestrator(session)

    # 4. Instantiate and start Agent Launcher
    launcher = AgentLauncher()
    launcher.start()

    # 5. Start the session
    orchestrator.start()

    # Allow some time for the first task (start) to finish and task_1 to start running
    # Poll for task_1 to be RUNNING. system.start might take time if not patched correctly.
    start_wait = time.time()
    task_1_running = False
    while time.time() - start_wait < 3.0:
        task_1_node = orchestrator.graph.node.get(f"{blueprint.id}.{task_1.id}")
        if task_1_node and task_1_node["task"].state == TaskState.RUNNING:
            task_1_running = True
            break
        time.sleep(0.1)

    assert task_1_running, "Task 1 should be RUNNING before we pause"

    # 6. Pause the orchestrator
    orchestrator.pause()

    assert orchestrator.state == BlueprintSessionState.STOPPED

    # Verify storage has updated state
    session_info = orchestrator.session_storage.get_session_info()
    assert session_info["state"] == BlueprintSessionState.STOPPED.value

    # Wait enough time for task_1 to definitely finish
    time.sleep(1.0)

    # At this point, task_1 should be SUCCEEDED, but task_2 should NOT be scheduled yet because we are paused.
    # We can check the internal graph or the session storage to verify task_1 state.
    # Note: The orchestrator instance still exists and receives the completion message,
    # but it won't schedule the next task.

    task_1_node = orchestrator.graph.node[f"{blueprint.id}.{task_1.id}"]
    task_1_state = task_1_node["task"].state
    assert task_1_state == TaskState.SUCCEEDED, "Task 1 should have completed even while paused"

    task_2_node = orchestrator.graph.node[f"{blueprint.id}.{task_2.id}"]
    task_2_state = task_2_node["task"].state
    assert task_2_state == TaskState.PENDING, "Task 2 should not have started yet"

    # 7. Resume (Start again)
    orchestrator.start()

    assert orchestrator.state == BlueprintSessionState.RUNNING

    # 8. Wait for completion
    completed = orchestrator.await_completion(timeout=5)
    assert completed, "Session should have completed after resuming"

    assert orchestrator.state == BlueprintSessionState.COMPLETED

    # Clean up
    orchestrator.stop()
    launcher.stop()


def test_orchestrator_stop(mock_immudb, mock_transport_orchestrator, mock_transport_launcher):
    # 1. Define a simple blueprint
    task_start = Task(id="start", type="system.start")
    task_1 = Task(id="task_1", type="system.sleep", params={"duration": 1.0})
    task_end = Task(id="end", type="system.end")

    task_start.then(task_1).then(task_end)

    blueprint = Blueprint(id="stop_bp", name="Stop Blueprint", tasks=[task_start, task_1, task_end])

    # 2. Create a session
    session = BlueprintSession(bsid="test_session_stop", blueprint=blueprint)

    # 3. Instantiate Orchestrator
    orchestrator = Orchestrator(session)

    # 4. Start Agent Launcher
    launcher = AgentLauncher()
    launcher.start()

    # 5. Start the session
    orchestrator.start()

    # 6. Stop the orchestrator immediately
    orchestrator.stop()

    assert orchestrator.session.state == BlueprintSessionState.STOPPED

    # Verify storage
    session_info = orchestrator.session_storage.get_session_info()
    assert session_info["state"] == BlueprintSessionState.STOPPED.value

    launcher.stop()
