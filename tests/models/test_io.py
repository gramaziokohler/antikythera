import json
import os
import tempfile

from compas.geometry import Frame

from antikythera.io import BlueprintJsonSerializer
from antikythera.models import Blueprint
from antikythera.models import Dependency
from antikythera.models import SystemTaskType
from antikythera.models import Task
from antikythera.models import TaskInput
from antikythera.models import TaskOutput
from antikythera.models import TaskParam


def test_roundtrip_blueprint():
    # Create a blueprint with some data including COMPAS types
    t1 = Task(id="start", type=SystemTaskType.START, outputs=[TaskOutput(name="frame", value=Frame.worldXY())])
    t2 = Task(id="end", type=SystemTaskType.END, depends_on=[Dependency(id="start")])

    bp = Blueprint(id="test_bp", name="Test Blueprint", tasks=[t1, t2])

    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "test_blueprint.json")

        # Write to file
        BlueprintJsonSerializer.to_file(bp, filepath)

        assert os.path.exists(filepath)

        # Read manually to check structure (should NOT be wrapped in {dtype:...})
        with open(filepath, "r") as f:
            data = json.load(f)
            assert data["id"] == "test_bp"
            assert "dtype" not in data

            tasks = data["tasks"]
            start_task = next(t for t in tasks if t["id"] == "start")
            output_val = start_task["outputs"][0]["value"]

            # COMPAS serialized object
            assert "dtype" in output_val and "compas.geometry" in output_val["dtype"]

        # Read back via parser
        bp_loaded = BlueprintJsonSerializer.from_file(filepath)

        assert bp_loaded.id == bp.id
        assert len(bp_loaded.tasks) == 2

        start_task_loaded = next(t for t in bp_loaded.tasks if t.id == "start")
        frame_loaded = start_task_loaded.outputs[0].value

        assert isinstance(frame_loaded, Frame)


def test_task_io_accepts_type_hint():
    for cls in (TaskInput, TaskOutput, TaskParam):
        io = cls(name="foo", type_hint="str")
        assert io.type_hint == "str"
        assert io.type == "str"


def test_task_io_accepts_deprecated_type():
    for cls in (TaskInput, TaskOutput, TaskParam):
        io = cls(name="foo", type="str")
        assert io.type_hint == "str"
        assert io.type == "str"


def test_task_io_serialisation_always_emits_type_hint():
    for cls in (TaskInput, TaskOutput, TaskParam):
        io = cls(name="foo", type="str")
        assert "type_hint" in BlueprintJsonSerializer.serialize(io)
        assert "type" not in BlueprintJsonSerializer.serialize(io)


def test_blueprint_loads_with_either_key_to_same_object():
    def make_blueprint_dict(io_key):
        return {
            "id": "test_bp",
            "name": "Test Blueprint",
            "version": "1.0",
            "tasks": [
                {
                    "id": "start",
                    "type": "system.start",
                    "outputs": [{"name": "frame", io_key: "compas.geometry.Frame"}],
                },
                {"id": "end", "type": "system.end", "depends_on": [{"id": "start"}]},
            ],
        }

    bp_type_hint = BlueprintJsonSerializer.BlueprintSerializer.from_dict(make_blueprint_dict("type_hint"))
    bp_type = BlueprintJsonSerializer.BlueprintSerializer.from_dict(make_blueprint_dict("type"))

    output_type_hint = bp_type_hint.tasks[0].outputs[0]
    output_type = bp_type.tasks[0].outputs[0]

    assert output_type_hint.type_hint == output_type.type_hint == "compas.geometry.Frame"
    assert output_type_hint.type == output_type.type == "compas.geometry.Frame"


def test_existing_blueprint_using_type_still_loads_and_roundtrips():
    data = {
        "id": "legacy_bp",
        "name": "Legacy Blueprint",
        "version": "1.0",
        "tasks": [
            {
                "id": "start",
                "type": "system.start",
                "outputs": [{"name": "greeting", "value": "hello", "type": "str"}],
            },
            {"id": "end", "type": "system.end", "depends_on": [{"id": "start"}]},
        ],
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "legacy_blueprint.json")
        with open(filepath, "w") as f:
            json.dump(data, f)

        blueprint = BlueprintJsonSerializer.from_file(filepath)
        output = blueprint.tasks[0].outputs[0]
        assert output.type_hint == "str"
        assert output.value == "hello"

        roundtrip_path = os.path.join(tmpdir, "roundtripped.json")
        BlueprintJsonSerializer.to_file(blueprint, roundtrip_path)

        with open(roundtrip_path, "r") as f:
            roundtripped = json.load(f)

        roundtripped_output = roundtripped["tasks"][0]["outputs"][0]
        assert roundtripped_output["type_hint"] == "str"
        assert "type" not in roundtripped_output
