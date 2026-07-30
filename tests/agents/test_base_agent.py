from unittest.mock import patch

from antikythera.models import Task
from antikythera.models import TaskParam
from antikythera_agents.annotations import Param
from antikythera_agents.base_agent import Agent
from antikythera_agents.context import ExecutionContext
from antikythera_agents.decorators import agent
from antikythera_agents.decorators import tool


@agent(type="test_binder")
class _BinderTestAgent(Agent):
    @tool(name="opaque")
    def opaque_tool(self, task: Task):
        return {"task_id": task.id}

    @tool(name="with_context")
    def with_context_tool(self, task: Task, context: ExecutionContext):
        return {"task_id": task.id, "has_context": context is not None}

    @tool(name="sleepy")
    def sleepy_tool(self, task: Task, duration: Param[float] = 1):
        return {"duration": duration}

    @tool(name="pnp.calculate_ik")
    def calculate_ik(self, task: Task):
        return {"tool": "calculate_ik"}


def test_task_only_tool_receives_task():
    a = _BinderTestAgent()
    task = Task(id="t1", type="test_binder.opaque")

    result = a.execute_task(task)

    assert result == {"task_id": "t1"}


def test_tool_annotated_task_and_context_receives_both():
    a = _BinderTestAgent()
    task = Task(id="t2", type="test_binder.with_context")
    context = ExecutionContext()

    result = a.execute_task(task, context)

    assert result == {"task_id": "t2", "has_context": True}


def test_param_binds_from_task_params():
    a = _BinderTestAgent()
    task = Task(id="t3", type="test_binder.sleepy", params=[TaskParam(name="duration", value=5)])

    result = a.execute_task(task)

    assert result == {"duration": 5}


def test_param_falls_back_to_default_when_task_omits_it():
    a = _BinderTestAgent()
    task = Task(id="t4", type="test_binder.sleepy")

    result = a.execute_task(task)

    assert result == {"duration": 1}


def test_dotted_tool_name_resolves_correctly():
    a = _BinderTestAgent()
    task = Task(id="t5", type="test_binder.pnp.calculate_ik")

    result = a.execute_task(task)

    assert result == {"tool": "calculate_ik"}


def test_execute_task_survives_monkeypatched_tool_method():
    """A test fixture may replace a tool method on the class with a Mock (as
    tests/orchestrator/conftest.py does for speed). Binding must keep working because the
    descriptor is captured from the class at `@agent` decoration time, not read off whatever
    object currently sits on the class.
    """
    with patch.object(_BinderTestAgent, "sleepy_tool") as mock_sleepy:
        mock_sleepy.return_value = {"duration": "mocked"}
        mock_sleepy._tool_name = "sleepy"

        a = _BinderTestAgent()
        task = Task(id="t6", type="test_binder.sleepy", params=[TaskParam(name="duration", value=9)])

        result = a.execute_task(task)

        assert result == {"duration": "mocked"}
        mock_sleepy.assert_called_once_with(a, task=task, duration=9)


def test_context_binds_even_when_none():
    """Regression guard: binding is driven by the descriptor's annotations, not by counting
    how many parameters the tool method accepts and whether a context happens to be given.
    The old arity check (`len(params) >= 3 and context is not None`) would have skipped
    binding `context` here and crashed the call with a missing required argument.
    """
    a = _BinderTestAgent()
    task = Task(id="t7", type="test_binder.with_context")

    result = a.execute_task(task, context=None)

    assert result == {"task_id": "t7", "has_context": False}
