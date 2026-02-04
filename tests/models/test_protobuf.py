from datetime import datetime

from compas.geometry import Frame
from compas_pb import pb_dump_bts
from compas_pb import pb_load_bts

from antikythera.models import TaskAssignmentMessage
from antikythera.models import TaskCompletionMessage
from antikythera.models import TaskError
from antikythera.models import TaskState

# Constant timestamp for testing
TEST_TIMESTAMP = datetime(2025, 10, 14, 12, 30, 45)


def test_taskassignment_to_pb():
    task_id = "Task123"
    task_type = "Computation"
    inputs = {"input1": [Frame.worldXY(), Frame.worldYZ()], "input2": "some_data"}
    output_keys = ["output1", "output2"]
    params = {"param1": True, "param2": 3.14}
    context = {"user": "tester", "priority": "high"}

    message = TaskAssignmentMessage(task_id, task_type, inputs, output_keys, params, context, timestamp=TEST_TIMESTAMP)

    msg_bts = pb_dump_bts(message)

    pb2 = pb_load_bts(msg_bts)

    assert pb2.id == task_id
    assert pb2.type == task_type
    assert pb2.inputs == inputs
    assert pb2.output_keys == output_keys
    assert pb2.params == params
    assert pb2.timestamp == TEST_TIMESTAMP


def test_taskcompletion_to_pb():
    task_id = "Task456"
    outputs = {"result1": [Frame.worldXY()], "result2": "computation_result"}
    error = TaskError(code="E001", message="Test error", details={"extra": "info"})
    duration_ms = 1500

    message = TaskCompletionMessage(id=task_id, state=TaskState.SUCCEEDED, outputs=outputs, error=error, timestamp=TEST_TIMESTAMP, duration_ms=duration_ms)

    msg_bts = pb_dump_bts(message)

    pb2 = pb_load_bts(msg_bts)

    assert pb2.id == task_id
    assert pb2.state == TaskState.SUCCEEDED
    assert pb2.outputs == outputs
    assert pb2.error.code == error.code
    assert pb2.error.message == error.message
    assert pb2.error.details == error.details
    assert pb2.timestamp == TEST_TIMESTAMP
    assert pb2.duration_ms == duration_ms
