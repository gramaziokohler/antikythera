import json

from antikythera.io import BlueprintJsonSerializer
from antikythera.models import Task


def test_task_condition_property():
    task = Task(id="test", type="system.test", condition="x == 1")
    assert task.condition == "x == 1"

    # Check serialization
    data = task.__data__
    assert data["condition"] == "x == 1"


def test_blueprint_serialization_with_condition(tmp_path):
    bp_dict = {
        "version": "1.0",
        "id": "bp1",
        "name": "Test BP",
        "tasks": [
            {"id": "start", "type": "system.start"},
            {"id": "t1", "type": "system.echo", "condition": "foo > 5", "depends_on": [{"id": "start"}]},
            {"id": "end", "type": "system.end", "depends_on": [{"id": "t1"}]},
        ],
    }

    # Write to file
    p = tmp_path / "bp.json"
    with open(p, "w") as f:
        json.dump(bp_dict, f)

    # Read back
    bp = BlueprintJsonSerializer.from_file(str(p))
    t1 = next(t for t in bp.tasks if t.id == "t1")

    assert t1.id == "t1"
    assert t1.condition == "foo > 5"


def test_condition_init_none():
    task = Task(id="test", type="system.test")
    assert task.condition is None
    data = task.__data__
    assert data["condition"] is None
