import json
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from .states import DependencyType
from .states import TaskState


@dataclass
class Dependency:
    """Represents a dependency of a task on another.

    Attributes
    ----------
    id : str
        The ID of the task this task depends on.
    type : DependencyType
        The type of dependency, by default DependencyType.FS (Finish-to-Start).

    """

    id: str
    type: DependencyType = DependencyType.FS


@dataclass
class Task:
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

    """

    id: str
    type: str
    description: Optional[str] = None
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[Dependency] = field(default_factory=list)
    params: Dict[str, Any] = field(default_factory=dict)
    state: TaskState = TaskState.PENDING


@dataclass
class Blueprint:
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

    id: str
    name: str
    version: str = "1.0"
    description: Optional[str] = None
    tasks: List[Task] = field(default_factory=list)


@dataclass
class BlueprintSession:
    """Represents a session of the execution of a blueprint.
    
    Attributes
    ----------
    bsid : str
        The ID of the blueprint session.
    blueprint : Blueprint
        The blueprint.
    """
    bsid: str
    blueprint: Blueprint


def _parse_task(task_def: Dict[str, Any]) -> Task:
    """Parses a task definition dictionary into a Task object."""
    known_fields = {"id", "type", "description", "depends_on", "params", "inputs", "outputs"}
    params = task_def.get("params", {})
    # Add any other unknown fields to params
    params.update({k: v for k, v in task_def.items() if k not in known_fields and not k.startswith("_")})

    dependencies_defs = task_def.get("depends_on", [])
    dependencies = []
    for dep_data in dependencies_defs:
        if 'type' in dep_data:
            dep_data['type'] = DependencyType(dep_data['type'])
        dependencies.append(Dependency(**dep_data))

    return Task(
        id=task_def["id"],
        type=task_def["type"],
        description=task_def.get("description"),
        inputs=task_def.get("inputs", {}),
        outputs=task_def.get("outputs", {}),
        depends_on=dependencies,
        params=params,
    )

def load_blueprint_from_file(filepath: str) -> Blueprint:
    """Loads a blueprint from a JSON file.

    Attributes
    ----------
    filepath : str
        The path to the JSON file.

    Returns
    -------
    Blueprint
        An instance of Blueprint.
    """
    with open(filepath, "r") as f:
        data = json.load(f)

    task_defs = data.get("tasks", [])
    tasks = [_parse_task(task_def) for task_def in task_defs]

    return Blueprint(
        id=data["id"],
        name=data["name"],
        description=data.get("description"),
        version=data.get("version", "1.0"),
        tasks=tasks,
    )
