import json
import os
from typing import Any
from typing import Dict

import jsonschema
from compas.data import json_dump
from compas.data import json_load

from antikythera.models.blueprints import Blueprint
from antikythera.models.blueprints import Dependency
from antikythera.models.blueprints import DependencyType
from antikythera.models.blueprints import Task
from antikythera.models.blueprints import TaskInput
from antikythera.models.blueprints import TaskOutput
from antikythera.models.blueprints import TaskParam
from antikythera.models.blueprints import TaskState

SCHEMA_FILE = os.path.join(os.path.dirname(__file__), "models", "schema.json")


class BlueprintJsonSerializer:
    """Handles Input/Output for Blueprint JSON files (Read, Write, Validate)."""

    @staticmethod
    def load_schema() -> Dict[str, Any]:
        """Load the JSON schema for Antikythera Blueprints."""
        if not os.path.exists(SCHEMA_FILE):
            raise FileNotFoundError(f"Schema file not found at {SCHEMA_FILE}")
        with open(SCHEMA_FILE, "r") as f:
            return json.load(f)

    @staticmethod
    def validate(data: Dict[str, Any]) -> None:
        """Validate a blueprint dictionary against the schema.

        Parameters
        ----------
        data : Dict[str, Any]
            The blueprint data to validation.

        Raises
        ------
        jsonschema.ValidationError
            If the data does not match the schema.
        """
        schema = BlueprintJsonSerializer.load_schema()
        jsonschema.validate(instance=data, schema=schema)

    @staticmethod
    def validate_file(filepath: str) -> None:
        """Validate a blueprint JSON file against the schema.

        Parameters
        ----------
        filepath : str
            Path to the JSON file.

        Raises
        ------
        jsonschema.ValidationError
            If the data does not match the schema.
        FileNotFoundError
            If the file does not exist.
        json.JSONDecodeError
            If the file is not valid JSON.
        """
        with open(filepath, "r") as f:
            data = json.load(f)
        BlueprintJsonSerializer.validate(data)

    @staticmethod
    def from_file(filepath: str, validate: bool = True) -> Blueprint:
        """Loads a blueprint from a Blueprint JSON file.

        Parameters
        ----------
        filepath : str
            The path to the Blueprint JSON file.
        validate : bool, optional
            Whether to validate the file against the schema, by default True.

        Returns
        -------
        Blueprint
            An instance of Blueprint.
        """
        with open(filepath, "r") as f:
            data = json_load(f)

        if isinstance(data, Blueprint):
            return data

        # If we reach here, it means it's a "Blueprint JSON" file format, not a COMPAS-serialized Blueprint
        if validate:
            BlueprintJsonSerializer.validate_file(filepath)

        task_defs = data.get("tasks", [])
        tasks = []
        for task_def in task_defs:
            if isinstance(task_def, Task):
                tasks.append(task_def)
            else:
                tasks.append(BlueprintJsonSerializer.parse_task(task_def))

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
    def _clean_data(data: Any) -> Any:
        """Recursively remove keys with None values or empty lists, and remove 'state' key."""
        if isinstance(data, dict):
            new_data = {}
            for k, v in data.items():
                if k == "state":
                    continue

                cleaned_v = BlueprintJsonSerializer._clean_data(v)

                if cleaned_v is None:
                    continue

                if isinstance(cleaned_v, list) and len(cleaned_v) == 0:
                    continue

                new_data[k] = cleaned_v
            return new_data

        elif isinstance(data, list):
            return [BlueprintJsonSerializer._clean_data(v) for v in data]
        else:
            return data

    @staticmethod
    def to_file(blueprint: Blueprint, filepath: str, pretty: bool = True) -> None:
        # We manually use __data__ to ensure we write the raw JSON structure
        # instead of a wrapped COMPAS object {"dtype": ..., "data": ...}
        # compas.data.json_dump will recursively handle inner COMPAS objects in values
        data = BlueprintJsonSerializer._clean_data(blueprint.__data__)
        json_dump(data, filepath, pretty=pretty)

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
