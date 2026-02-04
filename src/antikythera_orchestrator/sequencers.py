from __future__ import annotations

import logging
from abc import ABC
from abc import abstractmethod
from typing import TYPE_CHECKING
from typing import List

from antikythera.models import Blueprint
from antikythera.models import Dependency
from antikythera.models import Task
from antikythera_orchestrator.storage import ModelStorage

if TYPE_CHECKING:
    from antikythera.models import BlueprintSession


LOG = logging.getLogger(__name__)


class SequencerRegistry:
    _SEQUENCERS = {}

    @classmethod
    def register_sequencer(cls, name: str, sequencer_cls: type) -> None:
        if name in cls._SEQUENCERS:
            LOG.warning(f"Sequencer '{name}' is already registered. Overwriting.")
        cls._SEQUENCERS[name] = sequencer_cls

    @classmethod
    def get_sequencer(cls, name: str, *args, **kwargs):
        sequencer_cls = cls._SEQUENCERS.get(name)
        if not sequencer_cls:
            raise ValueError(f"Sequencer '{name}' is not registered.")
        return sequencer_cls(*args, **kwargs)


def sequencer(name: str):
    def decorator(cls):
        SequencerRegistry.register_sequencer(name, cls)
        return cls

    return decorator


class Sequencer(ABC):
    def __init__(self, session: "BlueprintSession"):
        self.session = session

    @abstractmethod
    def expand(self, task: Task, blueprint: Blueprint) -> Blueprint:
        raise NotImplementedError


@sequencer("basic_sequencer")
class BasicSequencer(Sequencer):
    def expand(self, task: Task, blueprint: Blueprint) -> Blueprint:
        elements = self.get_fabrication_items(blueprint.id)
        new_tasks = self._create_element_tasks(task, elements)
        self._update_blueprint_tasks(blueprint, task, new_tasks)
        return blueprint

    def get_fabrication_items(self, _: str) -> List:
        model_id = self.session.params.get("model_id")

        if not model_id:
            raise ValueError("model_id not found in session params or task params")

        with ModelStorage() as storage:
            model = storage.get_model(model_id)

        return list(model.elements())

    def _create_element_tasks(self, task: Task, elements: List) -> List[Task]:
        new_tasks = []
        previous_task_id = None
        original_dependencies = task.depends_on

        for i, element in enumerate(elements):
            element_id = str(element.guid)
            new_task_id = f"{task.id}_{i}"

            new_task = Task.from_dynamic_task(
                dynamic_task=task,
                new_task_id=new_task_id,
                element_id=element_id,
            )

            if previous_task_id is None:
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


@sequencer("basic_stock_sequencer")
class BasicStockSequencer(BasicSequencer):
    def get_fabrication_items(self, _: str) -> List:
        model_id = self.session.params.get("model_id")

        if not model_id:
            raise ValueError("model_id not found in session params or task params")

        with ModelStorage() as storage:
            nesting_result = storage.get_nesting(model_id)
            if not nesting_result:
                raise ValueError(f"Nesting result not found for model_id: {model_id}")

        return list(nesting_result.stocks)

    def _create_element_tasks(self, task: Task, elements: List) -> List[Task]:
        new_tasks = super()._create_element_tasks(task, elements)

        model_id = self.session.params.get("model_id")
        assert model_id is not None

        slab_name = None

        with ModelStorage() as storage:
            model = storage.get_model(model_id)
            slab_name = model.slabs[0].name
            for stock_index, task in enumerate(new_tasks):
                composite_options = task.get_param_value("blueprint")
                element_context = composite_options["dynamic"]["element"]
                element_context["slab_name"] = slab_name
                element_context["stock_name"] = f"R{stock_index:02d}"
                LOG.debug(f"Updated task {task.id} with slab_name: {slab_name}, stock_name: R{stock_index:02d}")

        return new_tasks


@sequencer("basic_element_sequencer")
class BasicElementSequencer(BasicSequencer):
    def get_fabrication_items(self, blueprint_id: str) -> List:
        """
        Retrieves elements for a specific stock.
        It expects the 'element' (stock_id) to be present in the session storage
        for the current blueprint context.
        """
        model_id = self.session.params.get("model_id")
        if not model_id:
            raise ValueError("model_id not found in session params")

        stock_id = self.session.blueprint_contexts[blueprint_id]["element_id"]

        with ModelStorage() as storage:
            nesting_result = storage.get_nesting(model_id)
            model = storage.get_model(model_id)
            if not nesting_result:
                raise ValueError(f"Nesting result not found for model_id: {model_id}")

        target_stock = None
        for stock in nesting_result.stocks:
            if str(stock.guid) == stock_id:
                target_stock = stock
                break

        if not target_stock:
            raise ValueError(f"Stock with ID {stock_id} not found in nesting result.")

        # HACK: we actually just need the keys but for the sake of not having to re-implement `_create_element_tasks` we return the full elements
        return [model.element_by_guid(guid) for guid in target_stock.element_data]
