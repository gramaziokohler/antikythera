from unittest.mock import MagicMock

from antikythera.models import Task
from antikythera.models import TaskState
from antikythera_actors.context import ExecutionContext
from antikythera_actors.descriptor import ToolBindingError
from antikythera_actors.launcher import ActorLauncher


def _bare_launcher() -> ActorLauncher:
    """An ActorLauncher with no MQTT transport, for unit-testing `_execute_task` in isolation."""
    launcher = ActorLauncher.__new__(ActorLauncher)
    launcher.launcher_id = "test-launcher"
    launcher.task_completion_publisher = MagicMock()
    launcher.actors = {}
    return launcher


def test_binding_failure_reports_tool_binding_error_code():
    launcher = _bare_launcher()
    actor = MagicMock()
    actor.execute_task.side_effect = ToolBindingError("Tool 'copy' input 'source' resolved to None; a value is required.")
    launcher.actors["io"] = actor

    task = Task(id="t1", type="io.copy")
    launcher._execute_task(task, "io", ExecutionContext())

    launcher.task_completion_publisher.publish.assert_called_once()
    (msg,), _ = launcher.task_completion_publisher.publish.call_args
    assert msg.state == TaskState.FAILED
    assert msg.error.code == "TOOL_BINDING_ERROR"
    assert "source" in msg.error.message


def test_tool_runtime_failure_reports_tool_failure_code():
    launcher = _bare_launcher()
    actor = MagicMock()
    actor.execute_task.side_effect = RuntimeError("boom")
    launcher.actors["io"] = actor

    task = Task(id="t1", type="io.copy")
    launcher._execute_task(task, "io", ExecutionContext())

    launcher.task_completion_publisher.publish.assert_called_once()
    (msg,), _ = launcher.task_completion_publisher.publish.call_args
    assert msg.state == TaskState.FAILED
    assert msg.error.code == "TOOL_FAILURE"
