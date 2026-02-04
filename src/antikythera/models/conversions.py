from typing import Any

from compas_pb.core import _deserialize_any
from compas_pb.core import _serializer_any
from compas_pb.registry import pb_deserializer
from compas_pb.registry import pb_serializer

from antikythera.proto import antikythera_pb2

from .blueprints import TaskInput
from .blueprints import TaskOutput
from .blueprints import TaskParam
from .tasks import ExecutionMode
from .tasks import TaskAllocationMessage
from .tasks import TaskAssignmentMessage
from .tasks import TaskClaimRequest
from .tasks import TaskCompletionAckMessage
from .tasks import TaskCompletionMessage
from .tasks import TaskError
from .tasks import TaskState


@pb_serializer(TaskAssignmentMessage)
def taskassignment_to_pb(
    message: TaskAssignmentMessage,
) -> antikythera_pb2.TaskAssignmentMessage:
    pb = antikythera_pb2.TaskAssignmentMessage()
    pb.id = message.id
    pb.type = message.type
    if message.inputs:
        for k, v in message.inputs.items():
            pb.inputs[k].CopyFrom(_serializer_any(v))
    if message.output_keys:
        pb.output_keys.extend(message.output_keys)
    if message.params:
        for k, v in message.params.items():
            pb.params[k].CopyFrom(_serializer_any(v))
    if message.context:
        for k, v in message.context.items():
            pb.context[k].CopyFrom(_serializer_any(v))
    if message.timestamp:
        pb.timestamp.FromDatetime(message.timestamp)
    pb.execution_mode = _execution_mode_to_pb(message.execution_mode)
    return pb


@pb_deserializer(antikythera_pb2.TaskAssignmentMessage)
def taskassignment_from_pb(
    pb: antikythera_pb2.TaskAssignmentMessage,
) -> TaskAssignmentMessage:
    inputs = {}
    output_keys = []
    params = {}
    context = {}

    for k, v in pb.inputs.items():
        inputs[k] = _deserialize_any(v)
    output_keys.extend(pb.output_keys)
    for k, v in pb.params.items():
        params[k] = _deserialize_any(v)
    for k, v in pb.context.items():
        context[k] = _deserialize_any(v)

    return TaskAssignmentMessage(
        id=pb.id,
        type=pb.type,
        inputs=inputs if inputs else None,
        output_keys=output_keys if output_keys else None,
        params=params if params else None,
        timestamp=pb.timestamp.ToDatetime() if pb.HasField("timestamp") else None,
        execution_mode=_execution_mode_from_pb(pb.execution_mode),
        context=context if context else None,
    )


def inputs_to_dict(inputs: list[TaskInput]) -> dict[str, Any]:
    """Convert a list of TaskInput to a dictionary."""
    return {i.name: i.value for i in inputs}


def dict_to_inputs(data: dict[str, Any]) -> list[TaskInput]:
    """Convert a dictionary to a list of TaskInput."""
    return [TaskInput(name=k, value=v) for k, v in data.items()]


def params_to_dict(params: list[TaskParam]) -> dict[str, Any]:
    """Convert a list of TaskParam to a dictionary."""
    return {p.name: p.value for p in params}


def dict_to_params(data: dict[str, Any]) -> list[TaskParam]:
    """Convert a dictionary to a list of TaskParam."""
    return [TaskParam(name=k, value=v) for k, v in data.items()]


def outputs_to_dict(outputs: list[TaskOutput]) -> dict[str, Any]:
    """Convert a list of TaskOutput to a dictionary."""
    return {o.name: o.value for o in outputs}


def dict_to_outputs(data: dict[str, Any]) -> list[TaskOutput]:
    """Convert a dictionary to a list of TaskOutput."""
    return [TaskOutput(name=k, value=v) for k, v in data.items()]


def keys_to_outputs(keys: list[str]) -> list[TaskOutput]:
    """Convert a list of keys to a list of TaskOutput."""
    return [TaskOutput(name=k) for k in keys]


def outputs_to_keys(outputs: list[TaskOutput]) -> list[str]:
    """Extract output keys from a list of TaskOutput."""
    return [o.name for o in outputs]


TASK_STATE_TO_PB = {
    TaskState.PENDING: antikythera_pb2.TaskState.TASK_STATE_PENDING,
    TaskState.READY: antikythera_pb2.TaskState.TASK_STATE_READY,
    TaskState.RUNNING: antikythera_pb2.TaskState.TASK_STATE_RUNNING,
    TaskState.SUCCEEDED: antikythera_pb2.TaskState.TASK_STATE_SUCCEEDED,
    TaskState.FAILED: antikythera_pb2.TaskState.TASK_STATE_FAILED,
}

TASK_STATE_FROM_PB = {v: k for k, v in TASK_STATE_TO_PB.items()}


EXECUTION_MODE_TO_PB = {
    ExecutionMode.EXCLUSIVE: antikythera_pb2.ExecutionMode.EXECUTION_MODE_EXCLUSIVE,
    ExecutionMode.COMPETITIVE: antikythera_pb2.ExecutionMode.EXECUTION_MODE_COMPETITIVE,
}

EXECUTION_MODE_FROM_PB = {v: k for k, v in EXECUTION_MODE_TO_PB.items()}


def _execution_mode_to_pb(mode: ExecutionMode) -> antikythera_pb2.ExecutionMode:
    return EXECUTION_MODE_TO_PB.get(mode, antikythera_pb2.ExecutionMode.EXECUTION_MODE_EXCLUSIVE)


def _execution_mode_from_pb(pb_mode: antikythera_pb2.ExecutionMode) -> ExecutionMode:
    return EXECUTION_MODE_FROM_PB.get(pb_mode, ExecutionMode.EXCLUSIVE)


def _task_state_to_pb(state: TaskState) -> antikythera_pb2.TaskState:
    return TASK_STATE_TO_PB.get(state, antikythera_pb2.TaskState.TASK_STATE_UNSPECIFIED)


def _task_state_from_pb(pb_state: antikythera_pb2.TaskState) -> TaskState:
    return TASK_STATE_FROM_PB.get(pb_state, TaskState.UNSPECIFIED)


@pb_serializer(TaskCompletionMessage)
def taskcompletion_to_pb(
    message: TaskCompletionMessage,
) -> antikythera_pb2.TaskCompletionMessage:
    pb = antikythera_pb2.TaskCompletionMessage()

    pb.id = message.id
    pb.state = _task_state_to_pb(message.state)
    if message.outputs:
        for k, v in message.outputs.items():
            pb.outputs[k].CopyFrom(_serializer_any(v))
    if message.error:
        pb.error.code = message.error.code
        pb.error.message = message.error.message
        if message.error.details:
            pb.error.details.CopyFrom(_serializer_any(message.error.details))
    if message.timestamp:
        pb.timestamp.FromDatetime(message.timestamp)
    if message.duration_ms is not None:
        pb.duration_ms = message.duration_ms
    if message.agent_id:
        pb.agent_id = message.agent_id
    return pb


@pb_deserializer(antikythera_pb2.TaskCompletionMessage)
def taskcompletion_from_pb(
    pb: antikythera_pb2.TaskCompletionMessage,
) -> TaskCompletionMessage:
    outputs = {}
    error = None

    for k, v in pb.outputs.items():
        outputs[k] = _deserialize_any(v)

    if pb.HasField("error"):
        error_details = _deserialize_any(pb.error.details) if pb.error.HasField("details") else None
        error = TaskError(code=pb.error.code, message=pb.error.message, details=error_details)

    return TaskCompletionMessage(
        id=pb.id,
        state=_task_state_from_pb(pb.state),
        agent_id=pb.agent_id,
        outputs=outputs if outputs else None,
        error=error,
        timestamp=pb.timestamp.ToDatetime() if pb.HasField("timestamp") else None,
        duration_ms=pb.duration_ms if pb.duration_ms > 0 else None,
    )


@pb_serializer(TaskClaimRequest)
def taskclaimrequest_to_pb(
    message: TaskClaimRequest,
) -> antikythera_pb2.TaskClaimRequest:
    pb = antikythera_pb2.TaskClaimRequest()
    pb.task_id = message.task_id
    pb.agent_id = message.agent_id
    if message.timestamp:
        pb.timestamp.FromDatetime(message.timestamp)
    return pb


@pb_deserializer(antikythera_pb2.TaskClaimRequest)
def taskclaimrequest_from_pb(pb: antikythera_pb2.TaskClaimRequest) -> TaskClaimRequest:
    return TaskClaimRequest(
        task_id=pb.task_id,
        agent_id=pb.agent_id,
        timestamp=pb.timestamp.ToDatetime() if pb.HasField("timestamp") else None,
    )


@pb_serializer(TaskAllocationMessage)
def taskallocation_to_pb(
    message: TaskAllocationMessage,
) -> antikythera_pb2.TaskAllocationMessage:
    pb = antikythera_pb2.TaskAllocationMessage()
    pb.task_id = message.task_id
    pb.assigned_agent_id = message.assigned_agent_id
    if message.timestamp:
        pb.timestamp.FromDatetime(message.timestamp)
    return pb


@pb_deserializer(antikythera_pb2.TaskAllocationMessage)
def taskallocation_from_pb(
    pb: antikythera_pb2.TaskAllocationMessage,
) -> TaskAllocationMessage:
    return TaskAllocationMessage(
        task_id=pb.task_id,
        assigned_agent_id=pb.assigned_agent_id,
        timestamp=pb.timestamp.ToDatetime() if pb.HasField("timestamp") else None,
    )


@pb_serializer(TaskCompletionAckMessage)
def taskcompletionack_to_pb(
    message: TaskCompletionAckMessage,
) -> antikythera_pb2.TaskCompletionAckMessage:
    pb = antikythera_pb2.TaskCompletionAckMessage()
    pb.id = message.id
    pb.state = _task_state_to_pb(message.state)
    pb.accepted_agent_id = message.accepted_agent_id
    if message.timestamp:
        pb.timestamp.FromDatetime(message.timestamp)
    return pb


@pb_deserializer(antikythera_pb2.TaskCompletionAckMessage)
def taskcompletionack_from_pb(
    pb: antikythera_pb2.TaskCompletionAckMessage,
) -> TaskCompletionAckMessage:
    return TaskCompletionAckMessage(
        id=pb.id,
        state=_task_state_from_pb(pb.state),
        accepted_agent_id=pb.accepted_agent_id,
        timestamp=pb.timestamp.ToDatetime() if pb.HasField("timestamp") else None,
    )
