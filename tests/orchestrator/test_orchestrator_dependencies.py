import time

from antikythera.models import Blueprint
from antikythera.models import BlueprintSession
from antikythera.models import Task
from antikythera_agents.launcher import AgentLauncher
from antikythera_orchestrator.orchestrator import Orchestrator


def test_parallel_execution(mock_immudb, mock_transport_orchestrator, mock_transport_launcher):
    # Blueprint: A and B run in parallel.
    # We use system.sleep

    task_start = Task(id="start", type="system.start")

    task_a = Task(id="task_a", type="system.sleep", params={"duration": 0.5})
    task_b = Task(id="task_b", type="system.sleep", params={"duration": 0.5})

    # Task C depends on A and B (Wait, explicit dependencies)
    task_c = Task(id="task_c", type="system.sleep", params={"duration": 0.1})

    task_end = Task(id="end", type="system.end")

    task_start.then(task_a)
    task_start.then(task_b)

    task_a.then(task_c)
    task_b.then(task_c)

    task_c.then(task_end)

    blueprint = Blueprint(id="parallel_bp", name="Parallel Blueprint", tasks=[task_start, task_a, task_b, task_c, task_end])

    session = BlueprintSession(bsid="test_session_parallel", blueprint=blueprint)
    orchestrator = Orchestrator(session)

    launcher = AgentLauncher()
    launcher.start()

    start_time = time.time()
    orchestrator.start()

    completed = orchestrator.await_completion(timeout=5)
    end_time = time.time()

    assert completed

    duration = end_time - start_time
    # If serial: start(1.0) + A(0.5) + B(0.5) + C(0.1) + end(1.0) = 3.1s (Assuming 1s for unpatched start/end)
    # If parallel: start(1.0) + max(A, B)(0.5) + C(0.1) + end(1.0) = 2.6s
    # Allow some overhead.

    # Note: Orchestrator processing + message passing overhead might be significant.
    # But 3.1s vs 2.6s is distinguishable if we have tight timing, but 2.6 is > 1.0.
    # We increase the limit to 3.0s to accommodate potential unpatched start/end delays while still verifying it's faster than serial (3.1s).
    print(f"Total duration: {duration:.3f}s")

    # Assert duration is less than serial sum (3.1s)
    assert duration < 3.0, f"Execution took {duration}s, expected parallel execution (< 3.0s)"

    orchestrator.stop()
    launcher.stop()
