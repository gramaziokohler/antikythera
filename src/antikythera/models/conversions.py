from compas_pb.core import _deserialize_any
from compas_pb.core import _serializer_any
from compas_pb.registry import pb_deserializer
from compas_pb.registry import pb_serializer

from antikythera.proto import antikythera_pb2

from .states import TaskAssignmentMessage


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
