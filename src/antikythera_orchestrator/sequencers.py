from abc import ABC
from abc import abstractmethod
from typing import TYPE_CHECKING
from typing import List

from antikythera.models import Blueprint
from antikythera.models import Dependency
from antikythera.models import Task
from antikythera.models import SystemTaskType
from antikythera_orchestrator.storage import ModelStorage

if TYPE_CHECKING:
    from antikythera.models import BlueprintSession


class Sequencer(ABC):
    def __init__(self, session: "BlueprintSession"):
        self.session = session

    @abstractmethod
    def expand(self, task: Task, blueprint: Blueprint) -> Blueprint:
        pass


class BasicSequencer(Sequencer):
    def expand(self, task: Task, blueprint: Blueprint) -> Blueprint:
        elements = self.get_model_elements()
        inner_blueprint_id = task.params["blueprint"]["dynamic"]["blueprint"]
        new_tasks = self._create_element_tasks(task, elements, inner_blueprint_id)
        self._update_blueprint_tasks(blueprint, task, new_tasks)
        return blueprint

    def get_model_elements(self) -> List:
        model_id = self.session.params.get("model_id")

        if not model_id:
            raise ValueError("model_id not found in session params or task params")

        with ModelStorage() as storage:
            model = storage.get_model(model_id)

        return list(model.elements())

    def _create_element_tasks(self, task: Task, elements: List, inner_blueprint_id: str) -> List[Task]:
        new_tasks = []
        previous_task_id = None
        original_dependencies = task.depends_on

        for i, element in enumerate(elements):
            element_id = str(element.guid)
            new_task_id = f"{task.id}_{i}"

            new_task_params = task.params.copy()
            new_task_params["blueprint"]["dynamic"]["blueprint_id"] = inner_blueprint_id
            new_task_params["blueprint"]["dynamic"]["expanded"] = True

            new_task_inputs = task.inputs.copy()
            new_task_inputs["element_id"] = element_id

            new_task = Task(
                id=new_task_id,
                type=SystemTaskType.COMPOSITE,
                description=f"{task.description} - {element_id}",
                params=new_task_params,
                inputs=new_task_inputs,
                outputs=task.outputs.copy(),
                depends_on=[],
            )

            if i == 0:
                new_task.depends_on = [d for d in original_dependencies]
            else:
                new_task.depends_on = [Dependency(id=previous_task_id)]

            new_tasks.append(new_task)
            previous_task_id = new_task_id
        
        return new_tasks

    def _update_blueprint_tasks(self, blueprint: Blueprint, original_task: Task, new_tasks: List[Task]) -> None:
        new_blueprint_tasks = []
        last_new_task = new_tasks[-1] if new_tasks else None

        for t in blueprint.tasks:
            if t.id == original_task.id:
                new_blueprint_tasks.extend(new_tasks)
            else:
                # Update dependencies that pointed to the expanded task
                new_deps = []
                for dep in t.depends_on:
                    if dep.id == original_task.id:
                        if last_new_task:
                            new_deps.append(Dependency(id=last_new_task.id, type=dep.type))
                    else:
                        new_deps.append(dep)
                t.depends_on = new_deps
                new_blueprint_tasks.append(t)

        blueprint.tasks = new_blueprint_tasks
