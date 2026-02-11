from __future__ import annotations

from copy import deepcopy
from enum import auto
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Union

from compas.data import Data

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


class TaskIO(Data):
    """Base class for task inputs, outputs, and parameters."""

    def __init__(self, name: str, value: Any = None, type: Optional[str] = None, description: Optional[str] = None):
        super().__init__()
        self.name = name
        self.value = value
        self.type = type
        self.description = description

    @property
    def __data__(self) -> Dict[str, Any]:
        data = {
            "name": self.name,
            "value": self.value,
            "type": self.type,
            "description": self.description,
        }
        return data


class TaskInput(TaskIO):
    def __init__(self, name: str, value: Any = None, type: Optional[str] = None, get_from: Optional[str] = None, description: Optional[str] = None):
        super().__init__(name, value, type, description)
        self.get_from = get_from

    @property
    def __data__(self) -> Dict[str, Any]:
        data = super().__data__
        data["get_from"] = self.get_from
        return data


class TaskOutput(TaskIO):
    def __init__(self, name: str, value: Any = None, type: Optional[str] = None, set_to: Optional[str] = None, description: Optional[str] = None):
        super().__init__(name, value, type, description)
        self.set_to = set_to

    @property
    def __data__(self) -> Dict[str, Any]:
        data = super().__data__
        data["set_to"] = self.set_to
        return data


class TaskParam(TaskIO):
    pass


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
    inputs : List[TaskInput], optional
        A list of inputs for the task.
    outputs : List[TaskOutput], optional
        A list of outputs for the task.
    depends_on : List[Dependency], optional
        A list of dependencies on other tasks.
    params : List[TaskParam], optional
        A list of task-specific parameters.

    """

    @property
    def __data__(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "description": self.description,
            "condition": self.condition,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "params": self.params,
            "depends_on": self.depends_on,
            "state": self.state,
        }

    def __init__(
        self,
        id: str,
        type: str,
        description: Optional[str] = None,
        condition: Optional[str] = None,
        inputs: List[TaskInput] = None,
        outputs: List[TaskOutput] = None,
        params: List[TaskParam] = None,
        depends_on: List[Dependency] = None,
        state: TaskState = TaskState.PENDING,
        context: Dict[str, Any] = None,
        **kwargs,
    ) -> None:
        super().__init__()
        self.id = id
        self.type = type
        self.description = description
        self.condition = condition
        self.inputs = inputs or []
        self.outputs = outputs or []
        self.params = params or []
        self.depends_on = depends_on or []
        self.state = TaskState(state)
        self.context = context or {}

    def get_input(self, name: str) -> Optional[TaskInput]:
        for task_input in self.inputs:
            if task_input.name == name:
                return task_input
        return None

    def get_output(self, name: str) -> Optional[TaskOutput]:
        for task_output in self.outputs:
            if task_output.name == name:
                return task_output
        return None

    def set_input_value(self, name: str, value: Any) -> None:
        task_input = self.get_input(name)
        if not task_input:
            raise ValueError(f"Input '{name}' not found in task '{self.id}'")
        task_input.value = value

    def set_output_value(self, name: str, value: Any) -> None:
        task_output = self.get_output(name)
        if task_output:
            task_output.value = value
        else:
            self.outputs.append(TaskOutput(name=name, value=value))

    def set_param_value(self, name: str, value: Any) -> None:
        param = self.get_param(name)
        if param:
            param.value = value
        else:
            self.params.append(TaskParam(name=name, value=value))

    def get_input_value(self, name: str, default: Any = None) -> Any:
        task_input = self.get_input(name)
        return task_input.value if task_input else default

    def get_output_value(self, name: str, default: Any = None) -> Any:
        task_output = self.get_output(name)
        return task_output.value if task_output else default

    def get_param_value(self, name: str, default: Any = None) -> Any:
        param = self.get_param(name)
        return param.value if param else default

    def __repr__(self):
        return f"Task(id={self.id}, type={self.type}, dependencies={self.depends_on})"

    def then(self, task: Union[Task, List[Task]], type: DependencyType = DependencyType.FS) -> Union[Task, List[Task]]:
        """Adds a dependency from the given task(s) to this task.

        Parameters
        ----------
        task : Task or List[Task]
            The task(s) that will depend on this task.
        type : DependencyType, optional
            The type of dependency, by default DependencyType.FS.

        Returns
        -------
        Task or List[Task]
            The task(s) that was passed in, to allow chaining.
        """
        targets = task if isinstance(task, list) else [task]
        for t in targets:
            t.depends_on.append(Dependency(id=self.id, type=type))
        return task

    def __rshift__(self, other: Union[Task, List[Task]]) -> Union[Task, List[Task]]:
        return self.then(other)

    def __rrshift__(self, other: Union[Task, List[Task]]) -> Task:
        sources = other if isinstance(other, list) else [other]
        for source in sources:
            self.depends_on.append(Dependency(id=source.id))
        return self

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

        blueprint_param = self.get_param_value("blueprint")
        if not blueprint_param:
            return False

        return "dynamic" in blueprint_param

    @property
    def is_dynamically_expanded(self) -> bool:
        if not self.is_composite:
            return False

        blueprint_param = self.get_param_value("blueprint")
        if not blueprint_param:
            return False

        dynamic_params = blueprint_param.get("dynamic", {})
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
        blueprint_param = dynamic_task.get_param_value("blueprint")
        assert blueprint_param, "Dynamic task missing 'blueprint' parameter"

        inner_blueprint_id = blueprint_param["dynamic"]["blueprint_id"]

        # Deepcopy params to avoid modifying the original task
        new_params = deepcopy(dynamic_task.params)

        # Determine index of blueprint param or find it in new list
        for p in new_params:
            if p.name == "blueprint":
                p.value["dynamic"]["blueprint_id"] = inner_blueprint_id
                p.value["dynamic"]["element"] = {"element_id": element_id}
                p.value["dynamic"]["expanded"] = True
                break

        return cls(
            id=new_task_id,
            type=SystemTaskType.COMPOSITE,
            description=f"{dynamic_task.description} - {element_id}",
            condition=dynamic_task.condition,
            params=new_params,
            inputs=deepcopy(dynamic_task.inputs),
            outputs=deepcopy(dynamic_task.outputs),
            depends_on=[],
        )

    def get_param(self, name: str) -> Optional[TaskParam]:
        for p in self.params:
            if p.name == name:
                return p
        return None


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
        if self.tasks:
            self.validate()

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


class BlueprintSessionState(StrEnum):
    """Enumeration of possible blueprint session states."""

    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    STOPPED = auto()


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
            "composite_to_inner_blueprint_map": self.composite_to_inner_blueprint_map,
            "blueprint_contexts": self.blueprint_contexts,
        }

    def __init__(
        self,
        bsid: str,
        blueprint: Blueprint,
        inner_blueprints: Dict[str, Blueprint] = None,
        state: BlueprintSessionState = BlueprintSessionState.PENDING,
        params: Dict[str, str] = None,
        composite_to_inner_blueprint_map: Dict[str, str] = None,
        blueprint_contexts: Dict[str, Any] = None,
    ) -> None:
        super().__init__()
        self.bsid = bsid
        self.blueprint = blueprint
        self.inner_blueprints = inner_blueprints or {}
        self.state = state
        self.params = params or {}
        self.composite_to_inner_blueprint_map = composite_to_inner_blueprint_map or {}
        self.blueprint_contexts = blueprint_contexts or {}

    def get_blueprint(self, blueprint_id: str) -> Optional[Blueprint]:
        if self.blueprint.id == blueprint_id:
            return self.blueprint
        return self.inner_blueprints.get(blueprint_id)

    def get_context_for_blueprint(self, blueprint_id: str) -> Optional[Dict]:
        """Returns the context for a given blueprint, if it exists."""
        return self.blueprint_contexts.get(blueprint_id)
