"""Unit tests for blueprint scope policies (skip, retry, while)."""

from typing import Any
from typing import Dict

import pytest

from antikythera.models import Blueprint
from antikythera.models import BlueprintSession
from antikythera.models import BlueprintSessionState
from antikythera.models import Task
from antikythera.models import TaskOutput
from antikythera.models import TaskParam
from antikythera.models import TaskState
from antikythera_agents.base_agent import Agent
from antikythera_agents.decorators import agent
from antikythera_agents.decorators import tool
from antikythera_agents.launcher import AgentLauncher
from antikythera_orchestrator.orchestrator import Orchestrator

# ---------------------------------------------------------------------------
# Custom agents for scope tests
# ---------------------------------------------------------------------------


@agent(type="scope_test")
class ScopeTestAgent(Agent):
    """Agent whose tools track how many times they have been called."""

    call_counts: Dict[str, int] = {}

    @tool(name="counted_task")
    def counted_task(self, task: Task) -> Dict[str, Any]:
        ScopeTestAgent.call_counts[task.id] = ScopeTestAgent.call_counts.get(task.id, 0) + 1
        return {}

    @tool(name="increment_counter")
    def increment_counter(self, task: Task) -> Dict[str, Any]:
        """Increment a counter stored in the task's outputs and return the new value."""
        current = ScopeTestAgent.call_counts.get("global_counter", 0) + 1
        ScopeTestAgent.call_counts["global_counter"] = current
        return {"counter": current}


@pytest.fixture(autouse=True)
def reset_call_counts():
    """Ensure the shared call counter is zeroed before every test."""
    ScopeTestAgent.call_counts.clear()
    yield
    ScopeTestAgent.call_counts.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_scope_skip_blueprint(skip_condition: str) -> Blueprint:
    """Blueprint: start -> scope_start (with condition) -> body -> scope_end -> end.

    The *condition* on scope_start controls whether the scope runs (True) or is
    skipped (False).
    """
    task_start = Task(id="start", type="system.start")
    task_scope_open = Task(
        id="scope_open",
        type="system.sleep",
        params=[TaskParam(name="duration", value=0)],
        condition=skip_condition,
        scope_start={},
    )
    task_body = Task(
        id="scope_body",
        type="scope_test.counted_task",
    )
    task_scope_close = Task(
        id="scope_close",
        type="system.sleep",
        params=[TaskParam(name="duration", value=0)],
        scope_end="scope_open",
    )
    task_end = Task(id="end", type="system.end")

    task_start >> task_scope_open >> task_body >> task_scope_close >> task_end

    return Blueprint(
        id="scope_skip_bp",
        name="Scope Skip Blueprint",
        tasks=[task_start, task_scope_open, task_body, task_scope_close, task_end],
    )


def _make_scope_retry_blueprint(retries: int) -> Blueprint:
    """Blueprint: start -> scope_start (retry_policy) -> body -> scope_end -> end."""
    task_start = Task(id="start", type="system.start")
    task_scope_open = Task(
        id="scope_open",
        type="system.sleep",
        params=[TaskParam(name="duration", value=0)],
        scope_start={"retry_policy": {"retries": retries}},
    )
    task_body = Task(
        id="scope_body",
        type="scope_test.counted_task",
    )
    task_scope_close = Task(
        id="scope_close",
        type="system.sleep",
        params=[TaskParam(name="duration", value=0)],
        scope_end="scope_open",
    )
    task_end = Task(id="end", type="system.end")

    task_start >> task_scope_open >> task_body >> task_scope_close >> task_end

    return Blueprint(
        id="scope_retry_bp",
        name="Scope Retry Blueprint",
        tasks=[task_start, task_scope_open, task_body, task_scope_close, task_end],
    )


def _make_scope_while_blueprint(condition: str, max_iterations: int = None) -> Blueprint:
    """Blueprint: start -> scope_start (while_policy) -> body (outputs counter) -> scope_end -> end."""
    task_start = Task(id="start", type="system.start")

    while_policy = {"condition": condition}
    if max_iterations is not None:
        while_policy["max_iterations"] = max_iterations

    task_scope_open = Task(
        id="scope_open",
        type="system.sleep",
        params=[TaskParam(name="duration", value=0)],
        scope_start={"while_policy": while_policy},
    )
    task_body = Task(
        id="scope_body",
        type="scope_test.increment_counter",
        outputs=[TaskOutput(name="counter", set_to="counter")],
    )
    task_scope_close = Task(
        id="scope_close",
        type="system.sleep",
        params=[TaskParam(name="duration", value=0)],
        scope_end="scope_open",
    )
    task_end = Task(id="end", type="system.end")

    task_start >> task_scope_open >> task_body >> task_scope_close >> task_end

    return Blueprint(
        id="scope_while_bp",
        name="Scope While Blueprint",
        tasks=[task_start, task_scope_open, task_body, task_scope_close, task_end],
    )


# ---------------------------------------------------------------------------
# Tests: skip policy
# ---------------------------------------------------------------------------


def test_scope_skip_when_condition_false(mock_immudb, mock_transport_orchestrator, mock_transport_launcher, cleanup_manager):
    """When scope_start condition is False the entire scope is skipped."""
    blueprint = _make_scope_skip_blueprint(skip_condition="1 == 2")  # always False → skip

    session = BlueprintSession(bsid="test_scope_skip_false", blueprint=blueprint)
    orchestrator = cleanup_manager.register(Orchestrator(session))
    launcher = cleanup_manager.register(AgentLauncher())
    launcher.start()

    orchestrator.start()
    completed = orchestrator.await_completion(timeout=10)

    assert completed, "Session did not complete in time"
    assert orchestrator.state == BlueprintSessionState.COMPLETED

    graph = orchestrator.graph
    scope_open_state = graph.node[f"{blueprint.id}.scope_open"]["task"].state
    scope_body_state = graph.node[f"{blueprint.id}.scope_body"]["task"].state
    scope_close_state = graph.node[f"{blueprint.id}.scope_close"]["task"].state

    assert scope_open_state == TaskState.SKIPPED, f"scope_open should be SKIPPED, got {scope_open_state}"
    assert scope_body_state == TaskState.SKIPPED, f"scope_body should be SKIPPED, got {scope_body_state}"
    assert scope_close_state == TaskState.SKIPPED, f"scope_close should be SKIPPED, got {scope_close_state}"

    # Body task never ran
    assert sum(ScopeTestAgent.call_counts.values()) == 0

    orchestrator.stop()
    launcher.stop()


def test_scope_skip_when_condition_true(mock_immudb, mock_transport_orchestrator, mock_transport_launcher, cleanup_manager):
    """When scope_start condition is True the scope runs (no skip, no loop)."""
    blueprint = _make_scope_skip_blueprint(skip_condition="1 == 1")  # always True → run

    session = BlueprintSession(bsid="test_scope_skip_true", blueprint=blueprint)
    orchestrator = cleanup_manager.register(Orchestrator(session))
    launcher = cleanup_manager.register(AgentLauncher())
    launcher.start()

    orchestrator.start()
    completed = orchestrator.await_completion(timeout=10)

    assert completed
    assert orchestrator.state == BlueprintSessionState.COMPLETED

    graph = orchestrator.graph
    assert graph.node[f"{blueprint.id}.scope_open"]["task"].state == TaskState.SUCCEEDED
    assert graph.node[f"{blueprint.id}.scope_body"]["task"].state == TaskState.SUCCEEDED
    assert graph.node[f"{blueprint.id}.scope_close"]["task"].state == TaskState.SUCCEEDED

    # Body ran exactly once (no loop, just the skip-policy variant which is skip OR run once)
    assert sum(ScopeTestAgent.call_counts.values()) == 1
    # No loop iterations recorded
    assert orchestrator.session.scope_iterations.get("scope_open", 0) == 0

    orchestrator.stop()
    launcher.stop()


# ---------------------------------------------------------------------------
# Tests: retry policy
# ---------------------------------------------------------------------------


def test_scope_retry_policy(mock_immudb, mock_transport_orchestrator, mock_transport_launcher, cleanup_manager):
    """Scope with retry_policy runs initial + retries times."""
    retries = 2
    blueprint = _make_scope_retry_blueprint(retries=retries)

    session = BlueprintSession(bsid="test_scope_retry", blueprint=blueprint)
    orchestrator = cleanup_manager.register(Orchestrator(session))
    launcher = cleanup_manager.register(AgentLauncher())
    launcher.start()

    orchestrator.start()
    completed = orchestrator.await_completion(timeout=15)

    assert completed, "Session did not complete in time"
    assert orchestrator.state == BlueprintSessionState.COMPLETED

    # scope_iterations records how many loops (re-runs) happened after the initial run
    assert orchestrator.session.scope_iterations.get("scope_open") == retries

    # The body task ran 1 (initial) + retries times
    expected_count = 1 + retries
    assert sum(ScopeTestAgent.call_counts.values()) == expected_count

    orchestrator.stop()
    launcher.stop()


def test_scope_retry_zero(mock_immudb, mock_transport_orchestrator, mock_transport_launcher, cleanup_manager):
    """Scope with retries=0 runs exactly once (no looping)."""
    blueprint = _make_scope_retry_blueprint(retries=0)

    session = BlueprintSession(bsid="test_scope_retry_zero", blueprint=blueprint)
    orchestrator = cleanup_manager.register(Orchestrator(session))
    launcher = cleanup_manager.register(AgentLauncher())
    launcher.start()

    orchestrator.start()
    completed = orchestrator.await_completion(timeout=10)

    assert completed
    assert orchestrator.state == BlueprintSessionState.COMPLETED
    assert sum(ScopeTestAgent.call_counts.values()) == 1
    assert orchestrator.session.scope_iterations.get("scope_open", 0) == 0

    orchestrator.stop()
    launcher.stop()


# ---------------------------------------------------------------------------
# Tests: while policy
# ---------------------------------------------------------------------------


def test_scope_while_policy_condition(mock_immudb, mock_transport_orchestrator, mock_transport_launcher, cleanup_manager):
    """Scope with while_policy loops while condition is True.

    The body task increments a counter stored in session storage.
    Condition: ``counter < 3`` → loop stops when counter reaches 3 (3 total runs).
    """
    blueprint = _make_scope_while_blueprint(condition="counter < 3")

    session = BlueprintSession(bsid="test_scope_while", blueprint=blueprint)
    orchestrator = cleanup_manager.register(Orchestrator(session))
    launcher = cleanup_manager.register(AgentLauncher())
    launcher.start()

    orchestrator.start()
    completed = orchestrator.await_completion(timeout=20)

    assert completed, "Session did not complete in time"
    assert orchestrator.state == BlueprintSessionState.COMPLETED

    # Counter incremented 3 times → 3 total loop iterations
    assert ScopeTestAgent.call_counts.get("global_counter") == 3
    # scope_iterations = number of loops after initial run = 2
    assert orchestrator.session.scope_iterations.get("scope_open") == 2

    orchestrator.stop()
    launcher.stop()


def test_scope_while_policy_max_iterations(mock_immudb, mock_transport_orchestrator, mock_transport_launcher, cleanup_manager):
    """max_iterations caps the while loop even if condition would remain True."""
    # condition is always True; max_iterations=3 → loop stops after 3 total runs
    blueprint = _make_scope_while_blueprint(condition="True", max_iterations=3)

    session = BlueprintSession(bsid="test_scope_while_max", blueprint=blueprint)
    orchestrator = cleanup_manager.register(Orchestrator(session))
    launcher = cleanup_manager.register(AgentLauncher())
    launcher.start()

    orchestrator.start()
    completed = orchestrator.await_completion(timeout=20)

    assert completed, "Session did not complete in time"
    assert orchestrator.state == BlueprintSessionState.COMPLETED

    assert ScopeTestAgent.call_counts.get("global_counter") == 3
    # 3 total runs → 2 loops after initial
    assert orchestrator.session.scope_iterations.get("scope_open") == 2

    orchestrator.stop()
    launcher.stop()
