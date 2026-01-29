import json
import os
import tempfile

from compas.geometry import Frame

from antikythera.io import BlueprintJsonSerializer
from antikythera.models import Blueprint
from antikythera.models import Dependency
from antikythera.models import SystemTaskType
from antikythera.models import Task
from antikythera.models import TaskOutput


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

            # Check inner compas object
            # Tasks logic in __data__ flattening is hand-rolled in Task.__data__
            # so it matches schema.
            # But values inside should utilize compas serialization
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
