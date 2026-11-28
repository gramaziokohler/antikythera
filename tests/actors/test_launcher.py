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


def test_task_is_only_claimed_by_an_actor_of_its_type():
    from compas_eve.codecs import ProtobufMessageCodec
    from compas_eve.memory import InMemoryTransport

    from antikythera.models import TaskAssignmentMessage
    from antikythera_actors import Actor
    from antikythera_actors import ActorLauncher
    from antikythera_actors import actor
    from antikythera_actors import tool

    @actor(type="claim_test_a")
    class First(Actor):
        @tool(name="shared")
        def shared(self) -> dict:
            return {}

    @actor(type="claim_test_b")
    class Second(Actor):
        @tool(name="shared")
        def shared(self) -> dict:
            return {}

    launcher = ActorLauncher(actor_types=["claim_test_a", "claim_test_b"], discover=False, transport=InMemoryTransport(codec=ProtobufMessageCodec()))
    launcher.task_claim_publisher.publish = lambda claim: None

    launcher.on_task_start(TaskAssignmentMessage(id="bp.t", type="claim_test_b.shared", inputs={}, output_keys=[], params={}, context={}))

    assert launcher.pending_claims["bp.t"][1] == "claim_test_b"


def test_lost_claims_are_forgotten_unless_competitive():
    from compas_eve.codecs import ProtobufMessageCodec
    from compas_eve.memory import InMemoryTransport

    from antikythera.models import TaskAllocationMessage
    from antikythera.models import TaskAssignmentMessage
    from antikythera_actors import Actor
    from antikythera_actors import actor
    from antikythera_actors import tool

    @actor(type="lost_claim_test")
    class Worker(Actor):
        @tool(name="work")
        def work(self) -> dict:
            return {}

    launcher = ActorLauncher(actor_types=["lost_claim_test"], discover=False, transport=InMemoryTransport(codec=ProtobufMessageCodec()))
    launcher.task_claim_publisher.publish = lambda claim: None

    launcher.on_task_start(TaskAssignmentMessage(id="bp.exclusive", type="lost_claim_test.work"))
    launcher.on_task_start(TaskAssignmentMessage(id="bp.competitive", type="lost_claim_test.work", params={"execution_mode": "COMPETITIVE"}))
    launcher.on_task_allocation(TaskAllocationMessage(task_id="bp.exclusive", assigned_actor_id="another-launcher"))
    launcher.on_task_allocation(TaskAllocationMessage(task_id="bp.competitive", assigned_actor_id="another-launcher"))

    assert list(launcher.pending_claims) == ["bp.competitive"]
