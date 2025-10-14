from datetime import datetime
from unittest.mock import patch

from compas.geometry import Frame

from antikythera.models import TaskAssignmentMessage, TaskCompletionMessage, TaskState

# Constant timestamp for testing
TEST_TIMESTAMP = datetime(2025, 10, 14, 12, 30, 45)


def test_taskassignment_to_pb():
    from compas_pb import pb_dump_bts, pb_load_bts

    task_id = "Task123"
    task_type = "Computation"
    inputs = {"input1": [Frame.worldXY(), Frame.worldYZ()], "input2": "some_data"}
    output_keys = ["output1", "output2"]
    params = {"param1": True, "param2": 3.14}

    message = TaskAssignmentMessage(task_id, task_type, inputs, output_keys, params, TEST_TIMESTAMP)

    msg_bts = pb_dump_bts(message)

    pb2 = pb_load_bts(msg_bts)

    assert pb2.id == task_id
    assert pb2.type == task_type
    assert pb2.inputs == inputs
    assert pb2.output_keys == output_keys
    assert pb2.params == params
    assert pb2.timestamp == TEST_TIMESTAMP
