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


class BaseSerializer:
    class TaskIOSerializer:
        @staticmethod
        def to_dict(obj: Any) -> Dict[str, Any]:
            data = {
                "name": obj.name,
                "value": obj.value,
                "type": obj.type,
                "description": obj.description,
            }
            return {k: v for k, v in data.items() if v is not None}

    class TaskInputSerializer:
        @staticmethod
        def to_dict(obj: TaskInput) -> Dict[str, Any]:
            data = BaseSerializer.TaskIOSerializer.to_dict(obj)
            if obj.get_from:
                data["get_from"] = obj.get_from
            return data

        @staticmethod
        def from_dict(data: Dict[str, Any]) -> TaskInput:
            return TaskInput(**data)

    class TaskOutputSerializer:
        @staticmethod
        def to_dict(obj: TaskOutput) -> Dict[str, Any]:
            data = BaseSerializer.TaskIOSerializer.to_dict(obj)
            if obj.set_to:
                data["set_to"] = obj.set_to
            return data

        @staticmethod
        def from_dict(data: Dict[str, Any]) -> TaskOutput:
            return TaskOutput(**data)

    class TaskParamSerializer:
        @staticmethod
        def to_dict(obj: TaskParam) -> Dict[str, Any]:
            return BaseSerializer.TaskIOSerializer.to_dict(obj)

        @staticmethod
        def from_dict(data: Dict[str, Any]) -> TaskParam:
            return TaskParam(**data)

    class DependencySerializer:
        @staticmethod
        def to_dict(obj: Dependency) -> Dict[str, Any]:
            return {"id": obj.id, "type": obj.type}

        @staticmethod
        def from_dict(data: Dict[str, Any]) -> Dependency:
            if "type" in data:
                data["type"] = DependencyType(data["type"])
            return Dependency(**data)

    class TaskSerializer:
        @staticmethod
        def to_dict(task: Task) -> Dict[str, Any]:
            data = {
                "id": task.id,
                "type": task.type,
                "description": task.description,
                "condition": task.condition,
            }

            if task.inputs:
                data["inputs"] = [BaseSerializer.TaskInputSerializer.to_dict(i) for i in task.inputs]
            if task.outputs:
                data["outputs"] = [BaseSerializer.TaskOutputSerializer.to_dict(o) for o in task.outputs]
            if task.params:
                data["params"] = [BaseSerializer.TaskParamSerializer.to_dict(p) for p in task.params]
            if task.depends_on:
                data["depends_on"] = [BaseSerializer.DependencySerializer.to_dict(d) for d in task.depends_on]

            return {k: v for k, v in data.items() if v is not None}

        @staticmethod
        def from_dict(data: Dict[str, Any]) -> Task:
            """Parses a task definition dictionary into a Task object."""
            raw_inputs = data.get("inputs", [])
            inputs = [BaseSerializer.TaskInputSerializer.from_dict(i) for i in raw_inputs]

            raw_outputs = data.get("outputs", [])
            outputs = [BaseSerializer.TaskOutputSerializer.from_dict(o) for o in raw_outputs]

            raw_params = data.get("params", [])
            params = [BaseSerializer.TaskParamSerializer.from_dict(p) for p in raw_params]

            raw_dependencies = data.get("depends_on", [])
            dependencies = [BaseSerializer.DependencySerializer.from_dict(d) for d in raw_dependencies]

            id = data["id"]
            state = data.get("state", TaskState.PENDING)
            if isinstance(state, str):
                try:
                    state = TaskState(state)
                except ValueError:
                    state = TaskState.PENDING

            return Task(
                id=id,
                type=data["type"],
                description=data.get("description"),
                condition=data.get("condition"),
                inputs=inputs,
                outputs=outputs,
                params=params,
                depends_on=dependencies,
                state=state,
            )

    class BlueprintSerializer:
        @staticmethod
        def to_dict(blueprint: Blueprint) -> Dict[str, Any]:
            data = {
                "id": blueprint.id,
                "name": blueprint.name,
                "version": blueprint.version,
                "description": blueprint.description,
                "tasks": [BaseSerializer.TaskSerializer.to_dict(t) for t in blueprint.tasks],
            }
            return {k: v for k, v in data.items() if v is not None}

        @staticmethod
        def from_dict(data: Dict[str, Any]) -> Blueprint:
            task_defs = data.get("tasks", [])
            tasks = []
            for task_def in task_defs:
                if isinstance(task_def, Task):
                    tasks.append(task_def)
                else:
                    tasks.append(BaseSerializer.TaskSerializer.from_dict(task_def))

            return Blueprint(
                id=data["id"],
                name=data["name"],
                version=data.get("version"),
                description=data.get("description"),
                tasks=tasks,
            )

    @staticmethod
    def serialize(obj: Any) -> Any:
        serializers = {
            Blueprint: BaseSerializer.BlueprintSerializer,
            Task: BaseSerializer.TaskSerializer,
            TaskInput: BaseSerializer.TaskInputSerializer,
            TaskOutput: BaseSerializer.TaskOutputSerializer,
            TaskParam: BaseSerializer.TaskParamSerializer,
            Dependency: BaseSerializer.DependencySerializer,
        }
        serializer = serializers.get(type(obj))
        if serializer:
            return serializer.to_dict(obj)
        raise ValueError(f"No serializer found for type {type(obj)}")


class BlueprintJsonSerializer(BaseSerializer):
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

        blueprint = BaseSerializer.BlueprintSerializer.from_dict(data)
        blueprint.validate()
        return blueprint

    @staticmethod
    def to_file(blueprint: Blueprint, filepath: str, pretty: bool = True) -> None:
        data = BaseSerializer.serialize(blueprint)
        json_dump(data, filepath, pretty=pretty)
