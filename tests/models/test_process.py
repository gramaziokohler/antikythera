import json
import pytest
from antikythera.models.process import (
    FabricationProcess,
    Task,
    Dependency,
    load_process_from_file,
)
from antikythera.models.states import DependencyType, TaskState


@pytest.fixture
def sample_process_json():
    """Provides a sample fabrication process as a dictionary."""
    return {
        "id": "test-proc-1",
        "name": "Test Process",
        "version": "0.1.0",
        "description": "A sample process for testing.",
        "tasks": [
            {"id": "TASK_A", "type": "test.task.a", "description": "First task"},
            {
                "id": "TASK_B",
                "type": "test.task.b",
                "depends_on": [{"id": "TASK_A", "type": "FS"}],
                "params": {"extra_param": "value"},
            },
        ],
    }


def test_load_process_from_file(tmp_path, sample_process_json):
    """Tests loading a FabricationProcess from a JSON file."""
    process_file = tmp_path / "process.json"
    with open(process_file, "w") as f:
        json.dump(sample_process_json, f)

    process = load_process_from_file(str(process_file))

    assert isinstance(process, FabricationProcess)
    assert process.id == "test-proc-1"
    assert process.name == "Test Process"
    assert len(process.tasks) == 2


def test_task_parsing(tmp_path, sample_process_json):
    """Tests that tasks are parsed correctly from the JSON file."""
    process_file = tmp_path / "process.json"
    with open(process_file, "w") as f:
        json.dump(sample_process_json, f)

    process = load_process_from_file(str(process_file))

    task_a = next(t for t in process.tasks if t.id == "TASK_A")
    task_b = next(t for t in process.tasks if t.id == "TASK_B")

    assert isinstance(task_a, Task)
    assert task_a.type == "test.task.a"
    assert task_a.state == TaskState.PENDING
    assert not task_a.depends_on

    assert isinstance(task_b, Task)
    assert task_b.type == "test.task.b"
    assert len(task_b.depends_on) == 1
    assert isinstance(task_b.depends_on[0], Dependency)
    assert task_b.depends_on[0].id == "TASK_A"
    assert task_b.depends_on[0].type == DependencyType.FS
    assert task_b.params == {"extra_param": "value"}
