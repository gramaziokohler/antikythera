"""Tests for the orchestrator re-dispatch polling loop (issue 02)."""

import time
from unittest.mock import MagicMock
from unittest.mock import patch

from antikythera import config as antikythera_config
from antikythera.models import Blueprint
from antikythera.models import BlueprintSession
from antikythera.models import BlueprintSessionState
from antikythera.models import Task
from antikythera.models import TaskAssignmentMessage
from antikythera.models import TaskClaimRequest
from antikythera.models import TaskState
from antikythera_agents.launcher import AgentLauncher
from antikythera_orchestrator.orchestrator import Orchestrator
from antikythera_orchestrator.orchestrator import RedispatchPoller

# ---------------------------------------------------------------------------
# Test 1 — dispatch tracking lifecycle
# ---------------------------------------------------------------------------


def test_dispatch_tracking_lifecycle(mock_storage, mock_transport_orchestrator, mock_transport_launcher, cleanup_manager):
    """Tracking entries are populated on dispatch and cleared on claim and on both reset paths."""
    task_start = Task(id="start", type="system.start")
    work_task = Task(id="work", type="agent.unclaimed")  # no agent registered for this type
    task_end = Task(id="end", type="system.end")
    task_start >> work_task >> task_end

    blueprint = Blueprint(id="tracking_bp", name="Tracking BP", tasks=[task_start, work_task, task_end])
    session = BlueprintSession(bsid="tracking_lifecycle_test", blueprint=blueprint)
    orchestrator = cleanup_manager.register(Orchestrator(session))

    launcher = cleanup_manager.register(AgentLauncher())
    launcher.start()
    orchestrator.start()

    fqn = f"{blueprint.id}.{work_task.id}"

    # Wait for work_task to appear in the poller's tracking dict (system.start finishes
    # via fast_system_agents mock, then work_task is scheduled READY with no agent to claim it)
    deadline = time.time() + 5.0
    while time.time() < deadline:
        with orchestrator._redispatch_poller._lock:
            if fqn in orchestrator._redispatch_poller._entries:
                break
        time.sleep(0.05)

    assert orchestrator.graph.node[fqn]["task"].state == TaskState.READY
    with orchestrator._redispatch_poller._lock:
        assert fqn in orchestrator._redispatch_poller._entries

    # --- claim path: on_task_claim should untrack the entry ---
    orchestrator.on_task_claim(TaskClaimRequest(task_id=fqn, agent_id="test-agent"))
    with orchestrator._redispatch_poller._lock:
        assert fqn not in orchestrator._redispatch_poller._entries

    # --- _reset_failed_tasks path: manually re-track, then reset ---
    # Task is now RUNNING (after claim). _reset_failed_tasks resets RUNNING → PENDING and untracks.
    dummy_msg = TaskAssignmentMessage(id=fqn, type=work_task.type)
    orchestrator._redispatch_poller.track(fqn, dummy_msg)
    with orchestrator._redispatch_poller._lock:
        assert fqn in orchestrator._redispatch_poller._entries

    orchestrator._reset_failed_tasks()
    with orchestrator._redispatch_poller._lock:
        assert fqn not in orchestrator._redispatch_poller._entries

    # --- reset_task_state path: manually re-track, then reset ---
    orchestrator._redispatch_poller.track(fqn, dummy_msg)
    orchestrator.reset_task_state(blueprint.id, work_task.id)
    with orchestrator._redispatch_poller._lock:
        assert fqn not in orchestrator._redispatch_poller._entries


# ---------------------------------------------------------------------------
# Test 2 — re-dispatch re-publishes with exponential backoff
# ---------------------------------------------------------------------------


def test_redispatch_publishes_with_backoff():
    """Re-publishes occur after the correct exponential delay, and not before the window closes."""
    publish_calls = []
    task_states = {"bp.work": TaskState.READY}

    poller = RedispatchPoller(
        publish_fn=lambda msg: publish_calls.append(msg),
        fail_fn=MagicMock(),
        get_task_state_fn=lambda fqn: task_states.get(fqn),
        base_delay=2,
        max_delay=90,
        max_redispatches=5,
        poll_interval=0.05,
    )

    message = TaskAssignmentMessage(id="bp.work", type="agent.do")
    poller.start()

    try:
        poller.track("bp.work", message)

        # Before the 2-second window (attempt 0): no re-publish expected
        time.sleep(0.2)
        assert len(publish_calls) == 0, "Must not re-dispatch before the 2 s window"

        # Backdate the entry by 3 s to satisfy the attempt-0 delay (2 s)
        with poller._lock:
            _, attempts, _ = poller._entries["bp.work"]
        assert attempts == 0
        with poller._lock:
            poller._entries["bp.work"] = (time.monotonic() - 3.0, 0, message)

        # Wait for the next poller tick to fire the re-dispatch
        deadline = time.time() + 2.0
        while time.time() < deadline and len(publish_calls) < 1:
            time.sleep(0.05)
        assert len(publish_calls) == 1, "Should re-dispatch once after attempt-0 window (2 s)"

        # Attempt is now 1; delay is 4 s — a short wait should NOT trigger another publish
        time.sleep(0.2)
        assert len(publish_calls) == 1, "Must not re-dispatch before the 4 s window (attempt 1)"

        # Verify attempt counter was incremented
        with poller._lock:
            _, attempts_after, _ = poller._entries["bp.work"]
        assert attempts_after == 1

        # Backdate by 5 s to satisfy the attempt-1 delay (4 s)
        with poller._lock:
            poller._entries["bp.work"] = (time.monotonic() - 5.0, 1, message)

        deadline = time.time() + 2.0
        while time.time() < deadline and len(publish_calls) < 2:
            time.sleep(0.05)
        assert len(publish_calls) == 2, "Should re-dispatch again after attempt-1 window (4 s)"

        with poller._lock:
            _, attempts_after2, _ = poller._entries["bp.work"]
        assert attempts_after2 == 2

    finally:
        poller.stop()


# ---------------------------------------------------------------------------
# Test 3 — NO_AGENT_CLAIMED failure after MAX_REDISPATCHES
# ---------------------------------------------------------------------------


def test_no_agent_claimed_session_fails(mock_storage, mock_transport_orchestrator, mock_transport_launcher, cleanup_manager):
    """Session transitions to FAILED with NO_AGENT_CLAIMED after MAX_REDISPATCHES unclaimed re-dispatches."""
    task_start = Task(id="start", type="system.start")
    work_task = Task(id="work", type="agent.unclaimed")
    task_end = Task(id="end", type="system.end")
    task_start >> work_task >> task_end

    blueprint = Blueprint(id="no_claim_bp", name="No Claim BP", tasks=[task_start, work_task, task_end])
    session = BlueprintSession(bsid="no_agent_claimed_test", blueprint=blueprint)

    # Use base_delay=0 so the delay formula gives 0 s for all attempts,
    # meaning every poller tick (1 s) immediately fires a re-dispatch or failure.
    # With max_redispatches=2: tick 1 → attempt 0→1, tick 2 → attempt 1→2, tick 3 → fail.
    with (
        patch.object(antikythera_config, "REDISPATCH_BASE_DELAY", 0),
        patch.object(antikythera_config, "MAX_REDISPATCHES", 2),
        patch.object(antikythera_config, "REDISPATCH_MAX_DELAY", 90),
    ):
        orchestrator = cleanup_manager.register(Orchestrator(session))

    launcher = cleanup_manager.register(AgentLauncher())
    launcher.start()
    orchestrator.start()

    # Session should fail within a few poller ticks plus message-passing overhead.
    completed = orchestrator.await_completion(timeout=15)

    assert completed, "Session should have completed (as FAILED) within the timeout"
    assert orchestrator.session.state == BlueprintSessionState.FAILED

    fqn = f"{blueprint.id}.{work_task.id}"
    assert orchestrator.graph.node[fqn]["task"].state == TaskState.FAILED
