import json
import pytest
from antikythera.models import Blueprint
from antikythera.models import Task
from antikythera.models import Dependency
from antikythera.models import DependencyType
from antikythera.models import TaskState
from antikythera.models import load_blueprint_from_file


@pytest.fixture
def sample_blueprint_json():
    return {
        "id": "test-proc-1",
        "name": "Test Blueprint",
        "version": "0.1.0",
        "description": "A sample blueprint for testing.",
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


def test_load_blueprint_from_file(tmp_path, sample_blueprint_json):
    blueprint_file = tmp_path / "blueprint.json"
    with open(blueprint_file, "w") as f:
        json.dump(sample_blueprint_json, f)

    blueprint = load_blueprint_from_file(str(blueprint_file))

    assert isinstance(blueprint, Blueprint)
    assert blueprint.id == "test-proc-1"
    assert blueprint.name == "Test Blueprint"
    assert len(blueprint.tasks) == 2


def test_task_parsing(tmp_path, sample_blueprint_json):
    blueprint_file = tmp_path / "blueprint.json"
    with open(blueprint_file, "w") as f:
        json.dump(sample_blueprint_json, f)

    blueprint = load_blueprint_from_file(str(blueprint_file))

    task_a = next(t for t in blueprint.tasks if t.id == "TASK_A")
    task_b = next(t for t in blueprint.tasks if t.id == "TASK_B")

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
