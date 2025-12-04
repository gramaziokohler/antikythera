from typing import Any
from typing import Dict
from typing import List
from typing import Optional

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        pass


from compas.data import Data
from compas.data import json_load

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

    @property
    def is_composite(self) -> bool:
        return self.type == SystemTaskType.COMPOSITE

    @property
    def is_start(self) -> bool:
        return self.type == SystemTaskType.START

    @property
    def is_end(self) -> bool:
        return self.type == SystemTaskType.END


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

    def __init__(
        self,
        id: str,
        name: str,
        version: str = "1.0",
        description: Optional[str] = None,
        tasks: List[Task] = None,
    ) -> None:
        super().__init__()
        self.id = id
        self.name = name
        self.version = version
        self.description = description
        self.tasks = tasks or []

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

        task_defs = data.get("tasks", [])
        tasks = [_parse_task(task_def) for task_def in task_defs]

        return cls(
            id=data["id"],
            name=data["name"],
            description=data.get("description"),
            tasks=tasks,
        )


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
