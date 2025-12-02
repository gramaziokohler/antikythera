from compas_pb.core import _deserialize_any
from compas_pb.core import _serializer_any
from compas_pb.registry import pb_deserializer
from compas_pb.registry import pb_serializer

from antikythera.proto import antikythera_pb2

from .tasks import TaskAssignmentMessage
from .tasks import TaskCompletionMessage
from .tasks import TaskError
from .tasks import TaskState


@pb_serializer(TaskAssignmentMessage)
def taskassignment_to_pb(message: TaskAssignmentMessage) -> antikythera_pb2.TaskAssignmentMessage:
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
    if message.timestamp:
        pb.timestamp.FromDatetime(message.timestamp)
    return pb


@pb_deserializer(antikythera_pb2.TaskAssignmentMessage)
def taskassignment_from_pb(pb: antikythera_pb2.TaskAssignmentMessage) -> TaskAssignmentMessage:
    inputs = {}
    output_keys = []
    params = {}

    for k, v in pb.inputs.items():
        inputs[k] = _deserialize_any(v)
    output_keys.extend(pb.output_keys)
    for k, v in pb.params.items():
        params[k] = _deserialize_any(v)

    return TaskAssignmentMessage(
        id=pb.id,
        type=pb.type,
        inputs=inputs if inputs else None,
        output_keys=output_keys if output_keys else None,
        params=params if params else None,
        timestamp=pb.timestamp.ToDatetime() if pb.HasField("timestamp") else None,
    )


TASK_STATE_TO_PB = {
    TaskState.PENDING: antikythera_pb2.TaskState.TASK_STATE_PENDING,
    TaskState.READY: antikythera_pb2.TaskState.TASK_STATE_READY,
    TaskState.RUNNING: antikythera_pb2.TaskState.TASK_STATE_RUNNING,
    TaskState.SUCCEEDED: antikythera_pb2.TaskState.TASK_STATE_SUCCEEDED,
    TaskState.FAILED: antikythera_pb2.TaskState.TASK_STATE_FAILED,
}

TASK_STATE_FROM_PB = {v: k for k, v in TASK_STATE_TO_PB.items()}


def _task_state_to_pb(state: TaskState) -> antikythera_pb2.TaskState:
    return TASK_STATE_TO_PB.get(state, antikythera_pb2.TaskState.TASK_STATE_UNSPECIFIED)


def _task_state_from_pb(pb_state: antikythera_pb2.TaskState) -> TaskState:
    return TASK_STATE_FROM_PB.get(pb_state, TaskState.UNSPECIFIED)


@pb_serializer(TaskCompletionMessage)
def taskcompletion_to_pb(message: TaskCompletionMessage) -> antikythera_pb2.TaskCompletionMessage:
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
    return pb


@pb_deserializer(antikythera_pb2.TaskCompletionMessage)
def taskcompletion_from_pb(pb: antikythera_pb2.TaskCompletionMessage) -> TaskCompletionMessage:
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
        outputs=outputs if outputs else None,
        error=error,
        timestamp=pb.timestamp.ToDatetime() if pb.HasField("timestamp") else None,
        duration_ms=pb.duration_ms if pb.duration_ms > 0 else None,
    )
