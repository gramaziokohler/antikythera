from typing import Any
from typing import Dict

from compas.data import json_load

from antikythera.models.blueprints import Blueprint
from antikythera.models.blueprints import Dependency
from antikythera.models.blueprints import DependencyType
from antikythera.models.blueprints import Task
from antikythera.models.blueprints import TaskInput
from antikythera.models.blueprints import TaskOutput
from antikythera.models.blueprints import TaskParam
from antikythera.models.blueprints import TaskState


class BlueprintJsonParser:
    """Parses blueprint definitions from Blueprint JSON files."""

    @staticmethod
    def from_file(filepath: str) -> Blueprint:
        """Loads a blueprint from a Blueprint JSON file.

        Parameters
        ----------
        filepath : str
            The path to the Blueprint JSON file.

        Returns
        -------
        Blueprint
            An instance of Blueprint.
        """
        with open(filepath, "r") as f:
            data = json_load(f)

        if isinstance(data, Blueprint):
            return data

        task_defs = data.get("tasks", [])
        tasks = []
        for task_def in task_defs:
            if isinstance(task_def, Task):
                tasks.append(task_def)
            else:
                tasks.append(BlueprintJsonParser.parse_task(task_def))

        blueprint = Blueprint(
            id=data["id"],
            name=data["name"],
            version=data.get("version"),
            description=data.get("description"),
            tasks=tasks,
        )

        # Validate effectively checks the graph structure
        blueprint.validate()
        return blueprint

    @staticmethod
    def parse_task(task_def: Dict[str, Any]) -> Task:
        """Parses a task definition dictionary into a Task object."""

        id = task_def["id"]

        # Handle inputs
        inputs = []
        raw_inputs = task_def.get("inputs", [])
        if not isinstance(raw_inputs, list):
            raise ValueError(f"Task '{id}' inputs must be a list of dictionaries.")
        for item in raw_inputs:
            if isinstance(item, dict):
                inputs.append(TaskInput(**item))
            else:
                raise ValueError(f"Task '{id}' input item must be a dictionary. Got {type(item)}")

        # Handle outputs
        outputs = []
        raw_outputs = task_def.get("outputs", [])
        if not isinstance(raw_outputs, list):
            raise ValueError(f"Task '{id}' outputs must be a list of dictionaries.")
        for item in raw_outputs:
            if isinstance(item, dict):
                outputs.append(TaskOutput(**item))
            else:
                raise ValueError(f"Task '{id}' output item must be a dictionary.")

        # Handle Params
        params = []
        raw_params = task_def.get("params", [])
        if not isinstance(raw_params, list):
            raise ValueError(f"Task '{id}' params must be a list of dictionaries.")
        for item in raw_params:
            if isinstance(item, dict):
                params.append(TaskParam(**item))
            else:
                raise ValueError(f"Task '{id}' param item must be a dictionary.")

        dependencies_defs = task_def.get("depends_on", [])
        dependencies = []
        for dep_data in dependencies_defs:
            if "type" in dep_data:
                dep_data["type"] = DependencyType(dep_data["type"])
            dependencies.append(Dependency(**dep_data))

        state = task_def.get("state", TaskState.PENDING)
        if isinstance(state, str):
            try:
                state = TaskState(state)
            except ValueError:
                state = TaskState.PENDING

        return Task(
            id=id,
            type=task_def["type"],
            description=task_def.get("description"),
            condition=task_def.get("condition"),
            inputs=inputs,
            outputs=outputs,
            params=params,
            depends_on=dependencies,
            state=state,
        )
