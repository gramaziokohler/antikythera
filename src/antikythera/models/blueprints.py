from __future__ import annotations

from copy import deepcopy
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from compas.data import Data
from compas.data import json_load

from antikythera.compat import StrEnum

from .tasks import DependencyType
from .tasks import SystemTaskType
from .tasks import TaskState


class Dependency(Data):
    """Represents a dependency of a task on another.

    Attributes
    ----------
    id : str
        The ID of the task this task depends on.
    type : DependencyType
        The type of dependency, by default DependencyType.FS (Finish-to-Start).

    """

    @property
    def __data__(self) -> Dict[str, Any]:
        return {"id": self.id, "type": self.type}

    def __init__(self, id: str, type: DependencyType = DependencyType.FS) -> None:
        super().__init__()
        self.id = id
        self.type = type

    def __repr__(self):
        return f"Dependency(id={self.id}, type={self.type})"


class Task(Data):
    """Represents a single task in a blueprint.

    Attributes
    ----------
    id : str
        Unique identifier for the task.
    type : str
        The type of the task, which determines the agent that will execute it.
    description : str, optional
        A human-readable description of the task.
    inputs : Dict[str, Any], optional
        A dictionary of input data keys for the task.
    outputs : Dict[str, Any], optional
        A dictionary of output data keys for the task.
    depends_on : List[Dependency], optional
        A list of dependencies on other tasks.
    params : Dict[str, Any], optional
        A dictionary of task-specific parameters.
    argument_mapping : Dict[str, Dict[str, str]], optional
        A dictionary to explicitly handle argument remapping configuration.

    """

    @property
    def __data__(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "description": self.description,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "depends_on": self.depends_on,
            "params": self.params,
            "argument_mapping": self.argument_mapping,
            "state": self.state,
        }

    def __init__(
        self,
        id: str,
        type: str,
        description: Optional[str] = None,
        inputs: Dict[str, Any] = None,
        outputs: Dict[str, Any] = None,
        depends_on: List[Dependency] = None,
        params: Dict[str, Any] = None,
        argument_mapping: Dict[str, Dict[str, str]] = None,
        state: TaskState = TaskState.PENDING,
    ) -> None:
        super().__init__()
        self.id = id
        self.type = type
        self.description = description
        self.inputs = inputs or {}
        self.outputs = outputs or {}
        self.depends_on = depends_on or []
        self.params = params or {}
        self.argument_mapping = argument_mapping or {}
        self.state = state

    def __repr__(self):
        return f"Task(id={self.id}, type={self.type}, dependencies={self.depends_on})"

    def then(self, task: Task, type: DependencyType = DependencyType.FS) -> Task:
        """Adds a dependency from the given task to this task.

        Parameters
        ----------
        task : Task
            The task that will depend on this task.
        type : DependencyType, optional
            The type of dependency, by default DependencyType.FS.

        Returns
        -------
        Task
            The task that was passed in, to allow chaining.
        """
        task.depends_on.append(Dependency(id=self.id, type=type))
        return task

    @property
    def is_composite(self) -> bool:
        return self.type == SystemTaskType.COMPOSITE

    @property
    def is_start(self) -> bool:
        return self.type == SystemTaskType.START

    @property
    def is_end(self) -> bool:
        return self.type == SystemTaskType.END

    @property
    def is_dynamic(self) -> bool:
        if not self.is_composite:
            return False

        blueprint_params = self.params.get("blueprint", {})
        return "dynamic" in blueprint_params

    @property
    def is_dynamically_expanded(self) -> bool:
        if not self.is_composite:
            return False

        dynamic_params = self.params.get("blueprint", {}).get("dynamic", {})
        return dynamic_params.get("expanded", False)

    @classmethod
    def from_dynamic_task(cls, dynamic_task: Task, new_task_id: str, element_id: str) -> Task:
        """Creates a new dynamically expanded task from a composite task.

        Parameters
        ----------
        dynamic_task : Task
            The original composite task to expand.
        new_task_id : str
            The ID for the new expanded task.
        element_id : str
            The element ID to associate with the new task.

        Returns
        -------
        Task
            The newly created expanded task.

        """
        inner_blueprint_id = dynamic_task.params["blueprint"]["dynamic"]["blueprint"]

        new_task_params = deepcopy(dynamic_task.params)
        new_task_params["blueprint"]["dynamic"]["blueprint_id"] = inner_blueprint_id
        new_task_params["blueprint"]["dynamic"]["element"] = {"element_id": element_id}
        new_task_params["blueprint"]["dynamic"]["expanded"] = True

        return cls(
            id=new_task_id,
            type=SystemTaskType.COMPOSITE,
            description=f"{dynamic_task.description} - {element_id}",
            params=new_task_params,
            inputs=deepcopy(dynamic_task.inputs),
            outputs=deepcopy(dynamic_task.outputs),
            depends_on=[],
        )

    def try_get_element_id(self) -> str:
        """Returns the element_id of a dynamically expanded task, or None if not applicable."""
        return self.params.get("blueprint", {}).get("dynamic", {}).get("element", {}).get("element_id")


class Blueprint(Data):
    """Represents a complete blueprint.

    Attributes
    ----------
    id : str
        Unique identifier for the blueprint.
    name : str
        A human-readable name for the blueprint.
    version : str
        The version of the blueprint schema.
    description : str, optional
        A human-readable description of the blueprint.
    tasks : List[Task], optional
        A list of tasks that make up the blueprint.

    """

    @property
    def __data__(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "tasks": self.tasks,
        }

    @classmethod
    def __from_data__(cls, data: Dict[str, Any]) -> "Blueprint":
        # TODO: revisit this method, it's not really aligned with COMPAS Data patterns
        task_defs = data.get("tasks", [])
        tasks = []
        for task_def in task_defs:
            if isinstance(task_def, Task):
                tasks.append(task_def)
            else:
                tasks.append(_parse_task(task_def))

        return cls(
            id=data["id"],
            name=data["name"],
            version=data.get("version"),
            description=data.get("description"),
            tasks=tasks,
        )

    def __init__(
        self,
        id: str,
        name: str,
        version: Optional[str] = "1.0",
        description: Optional[str] = None,
        tasks: List[Task] = None,
    ) -> None:
        super().__init__()
        self.id = id
        self.name = name
        self.version = version
        self.description = description
        self.tasks = tasks or []

    def validate(self) -> None:
        """Validates the blueprint structure.

        Raises
        ------
        ValueError
            If the blueprint is invalid.
        """
        start_tasks = [t for t in self.tasks if t.type == SystemTaskType.START]
        end_tasks = [t for t in self.tasks if t.type == SystemTaskType.END]

        if len(start_tasks) != 1:
            raise ValueError(f"Blueprint must have exactly one start task, found {len(start_tasks)}.")
        if len(end_tasks) != 1:
            raise ValueError(f"Blueprint must have exactly one end task, found {len(end_tasks)}.")

        task_ids = {t.id for t in self.tasks}

        for task in self.tasks:
            if task.type != SystemTaskType.START and not task.depends_on:
                raise ValueError(f"Task '{task.id}' is an orphan (no dependencies) and is not a start task.")

            for dep in task.depends_on:
                if dep.id not in task_ids:
                    raise ValueError(f"Task '{task.id}' depends on non-existent task '{dep.id}'.")

    @classmethod
    def from_file(cls, filepath: str) -> "Blueprint":
        """Loads a blueprint from a JSON file.

        Args:
            filepath: The path to the JSON file.

        Returns:
            An instance of Blueprint.
        """
        with open(filepath, "r") as f:
            data = json_load(f)

        if isinstance(data, cls):
            return data

        blueprint = cls.__from_data__(data)
        blueprint.validate()
        return blueprint


class BlueprintSessionState(StrEnum):
    """Enumeration of possible blueprint session states."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    STOPPED = "STOPPED"


class BlueprintSession(Data):
    """Represents a session of the execution of a blueprint.

    Attributes
    ----------
    bsid : str
        The ID of the blueprint session.
    blueprint : Blueprint
        The blueprint.
    inner_blueprints : Dict[str, Blueprint], optional
        A dictionary of inner blueprints used in this session.
    """

    @property
    def __data__(self) -> Dict[str, Any]:
        return {
            "bsid": self.bsid,
            "blueprint": self.blueprint,
            "inner_blueprints": self.inner_blueprints,
            "state": self.state,
            "params": self.params,
        }

    def __init__(
        self,
        bsid: str,
        blueprint: Blueprint,
        inner_blueprints: Dict[str, Blueprint] = None,
        state: BlueprintSessionState = BlueprintSessionState.PENDING,
        params: Dict[str, str] = None,
    ) -> None:
        super().__init__()
        self.bsid = bsid
        self.blueprint = blueprint
        self.inner_blueprints = inner_blueprints or {}
        self.state = state
        self.params = params or {}


def _parse_task(task_def: Dict[str, Any]) -> Task:
    """Parses a task definition dictionary into a Task object."""
    known_fields = {"id", "type", "description", "depends_on", "params", "inputs", "outputs", "argument_mapping"}
    params = task_def.get("params", {})
    # Add any other unknown fields to params
    params.update({k: v for k, v in task_def.items() if k not in known_fields and not k.startswith("_")})

    dependencies_defs = task_def.get("depends_on", [])
    dependencies = []
    for dep_data in dependencies_defs:
        if "type" in dep_data:
            dep_data["type"] = DependencyType(dep_data["type"])
        dependencies.append(Dependency(**dep_data))

    return Task(
        id=task_def["id"],
        type=task_def["type"],
        description=task_def.get("description"),
        inputs=task_def.get("inputs", {}),
        outputs=task_def.get("outputs", {}),
        depends_on=dependencies,
        params=params,
        argument_mapping=task_def.get("argument_mapping", {}),
        state=TaskState.PENDING,
    )
