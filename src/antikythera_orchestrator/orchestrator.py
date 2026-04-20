from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from queue import Empty
from queue import LifoQueue
from queue import Queue
from typing import Any
from typing import Dict
from typing import Optional
from typing import Tuple
from typing import cast

from compas.datastructures import Graph
from compas_eve import Publisher
from compas_eve import Subscriber
from compas_eve import Topic
from compas_eve.codecs import ProtobufMessageCodec
from compas_eve.mqtt import MqttTransport
from compas_model.models import Model

from antikythera.models import Blueprint
from antikythera.models import BlueprintSession
from antikythera.models import BlueprintSessionState
from antikythera.models import Dependency
from antikythera.models import DependencyType
from antikythera.models import ExecutionMode
from antikythera.models import Task
from antikythera.models import TaskAllocationMessage
from antikythera.models import TaskAssignmentMessage
from antikythera.models import TaskClaimRequest
from antikythera.models import TaskCompletionAckMessage
from antikythera.models import TaskCompletionMessage
from antikythera.models import TaskState
from antikythera.models.conversions import outputs_to_keys
from antikythera.models.conversions import params_to_dict

from .conditionals import safe_eval_condition
from .scopes import ScopeRegistry
from .sequencers import SequencerRegistry
from .storage import BlueprintStorage
from .storage import ModelStorage
from .storage import SessionStorage

LOG = logging.getLogger(__name__)


def _get_eve_transport(host, port, codec):
    return MqttTransport(host=host, port=port, codec=codec)


def _create_global_id(blueprint_id: str, task: Task) -> str:
    """Creates a globally unique identifier for a task.

    This is useful when dealing with inner blueprints to avoid ID collisions.

    Parameters
    ----------
    blueprint_id : str
        The ID of the blueprint to which the task belongs.
    task : Task
        The task for which to create a global ID.

    Returns
    -------
    str
        The globally unique identifier for the task.
    """
    return f"{blueprint_id}.{task.id}"


@dataclass
class PendingTask:
    """Represents a task that is pending execution.

    Attributes
    ----------
    blueprint_id : str
        The ID of the blueprint to which the task belongs.
    task : Task
        The task that is pending execution.
    """

    blueprint_id: str
    task: Task


@dataclass
class ProcessedTask:
    """Represents a task that has been processed.

    Attributes
    ----------
    task_id : str
        The globally unique ID of the task.
    blueprint_id : str
        The ID of the blueprint to which the task belongs.
    task: Task
        The task that has been processed.
    """

    task_id: str
    blueprint_id: str
    task: Task


class TaskScheduler:
    """Task scheduler with support for FS and SS task dependencies."""

    def __init__(self, session: BlueprintSession, graph: Graph) -> None:
        self.session = session
        self.graph = graph
        self.queue = LifoQueue()
        self._lock = threading.Lock()

    def queue_message(self, message: TaskCompletionMessage) -> None:
        self.queue.put(message)

    def _are_ff_deps_fulfilled(self, dependencies) -> bool:
        # Check if all Finish-to-Finish dependencies are fulfilled
        # TODO: handle failed dependencies, should probably result in task failure
        ff_deps = [dep for dep in dependencies if dep.type == DependencyType.FF]

        all_ff_succeeded = True
        for dep in ff_deps:
            dep_task = self.graph.node[dep.id]["task"]

            if dep_task.state not in (TaskState.SUCCEEDED, TaskState.SKIPPED):
                all_ff_succeeded = False
                break
        return all_ff_succeeded

    def _process_message(self, message: TaskCompletionMessage, task: Task, blueprint_id: str) -> ProcessedTask:
        # THIS METHOD MUTATES `task`
        # updated the task state according to the reported state in the message
        # create and return a ProcessedTask object
        if message.state not in (TaskState.SUCCEEDED, TaskState.FAILED, TaskState.SKIPPED):
            raise ValueError(f"Invalid task state: {message.state}")

        task.state = TaskState(message.state)
        if message.outputs:
            for k, v in message.outputs.items():
                task.set_output_value(k, v)

        return ProcessedTask(task_id=task.id, blueprint_id=blueprint_id, task=task)

    def process_queue(self) -> list[ProcessedTask]:
        processed_tasks = []
        put_back_to_queue = []

        while not self.queue.empty():
            message = self.queue.get()

            task_id = message.id
            task = self.graph.node[task_id]["task"]
            blueprint_id = self.graph.node[task_id]["blueprint_id"]

            # TODO: Handle task failure properly

            dependencies = self._get_dependencies_from_graph(blueprint_id, task)
            has_ff_deps = any(dep.type == DependencyType.FF for dep in dependencies)
            if not has_ff_deps or self._are_ff_deps_fulfilled(dependencies):
                # task has no FF dependencies, or it has but they are fulfilled => we can process it right away
                processed_task = self._process_message(message, task, blueprint_id)
                processed_tasks.append(processed_task)
            else:
                # still waiting on FF dependencies, put back to the stack for later processing
                put_back_to_queue.append(message)

        for message in put_back_to_queue:
            self.queue.put(message)

        return processed_tasks

    def get_pending_tasks(self) -> list[PendingTask]:
        """Returns a list of tasks that are pending execution whose dependencies are satisfied."""
        pending_tasks = []

        for task, blueprint_id in self.graph.nodes_attributes(("task", "blueprint_id")):
            if task.state not in (TaskState.PENDING, TaskState.SKIP_REQUESTED):
                continue

            dependencies = self._get_dependencies_from_graph(blueprint_id, task)
            dependency_preconditions = []

            for dep in dependencies:
                dep_task = self.graph.node[dep.id]["task"]
                dependency_type = dep.type

                if dependency_type == DependencyType.FS:
                    dependency_preconditions.append(dep_task.state in (TaskState.SUCCEEDED, TaskState.SKIPPED))
                elif dependency_type == DependencyType.SS:
                    dependency_preconditions.append(dep_task.state in (TaskState.RUNNING, TaskState.SUCCEEDED, TaskState.SKIPPED))
                # NOTE: Finish-type dependencies (ie. FF and SF) are implemented in the queue processing stage

            if all(dependency_preconditions):
                pending_tasks.append(PendingTask(blueprint_id=blueprint_id, task=task))

        return pending_tasks

    def _get_dependencies_from_graph(self, blueprint_id: str, task: Task) -> list[Dependency]:
        fqn_task_id = _create_global_id(blueprint_id, task)
        neighbors = self.graph.neighbors_in(fqn_task_id)
        dependencies = []

        for fqn_dep_task_id in neighbors:
            dependency_type = self.graph.edge_attribute((fqn_dep_task_id, fqn_task_id), "type")
            dependencies.append(Dependency(id=fqn_dep_task_id, type=dependency_type))

        return dependencies

    def _create_mermaid_task_id(self, blueprint_id: str, task: Task) -> str:
        return _create_global_id(blueprint_id, task).replace(".", "_")

    def to_mermaid_diagram(self, title="Blueprint") -> str:
        """Generate a mermaid-syntax diagram representation of the blueprint session.

        For more info about Mermaid syntax: https://mermaid.js.org

        Returns
        -------
        str
            Gantt chart representation of the blueprint session.
        """
        import datetime

        from compas.topology import breadth_first_traverse

        if not self.graph:
            return

        result = list()
        result.append(f"gantt\n  title    {title}")

        def create_label(blueprint_id: str, task: Task):
            if task.state == TaskState.SUCCEEDED:
                task_state = "✅"
            elif task.state == TaskState.FAILED:
                task_state = "❌"
            elif task.state == TaskState.PENDING:
                task_state = "⏳"
            elif task.state == TaskState.READY:
                task_state = "🏁"
            elif task.state == TaskState.RUNNING:
                task_state = "🏃"
            else:
                task_state = "?"
            task_label = f"{task_state} [{self._create_mermaid_task_id(blueprint_id, task)}] {task.type}"
            return task_label

        def append_node(previous, current):
            task: Task = self.graph.node[current]["task"]
            blueprint_id = self.graph.node[current]["blueprint_id"]
            task_label = create_label(blueprint_id, task)

            dependencies_list = []

            for node_in in self.graph.neighbors_in(current):
                task_in = self.graph.node[node_in]["task"]
                dependencies_list.append(self._create_mermaid_task_id(blueprint_id, task_in))

            if dependencies_list:
                dependencies = "after " + " ".join(dependencies_list)
            else:
                dependencies = ""

            milestone = ""
            if task.is_start or task.is_end:
                milestone = "milestone, "
                duration = "0d"
            else:
                duration = "1d"
            if task.is_start and dependencies == "":
                dependencies = datetime.datetime.now(datetime.timezone.utc).date().isoformat()

            result.append("  {:40}   : {}{}, {}, {}".format(task_label, milestone, self._create_mermaid_task_id(blueprint_id, task), dependencies, duration))

        root_node = None
        for node in self.graph.nodes():
            if self.graph.degree_in(node) == 0:
                root_node = node
                append_node(None, root_node)
                break

        breadth_first_traverse(self.graph.adjacency, root_node, append_node)

        return "\n".join(result)


class Orchestrator:
    """Coordinates the execution of a blueprint.

    The orchestrator is responsible for managing the state of a blueprint session,
    and coordinating the execution of tasks by agents.

    Attributes
    ----------
    session : BlueprintSession
        The blueprint session to execute.

    """

    _INSTANCES = []
    _LOCK = threading.Lock()

    def __init__(self, session: BlueprintSession, broker_host="127.0.0.1", broker_port=1883) -> None:
        super(Orchestrator, self).__init__()
        self.session: BlueprintSession = session
        self.graph: Graph = None
        self._completion_event = threading.Event()

        self.transport = _get_eve_transport(host=broker_host, port=broker_port, codec=ProtobufMessageCodec())
        self.task_start = Topic("antikythera/task/start")
        self.task_completed = Topic("antikythera/task/completed")
        self.task_claim = Topic("antikythera/task/claim")
        self.task_allocation = Topic("antikythera/task/allocation")
        self.task_ack = Topic("antikythera/task/ack")

        self.task_start_publisher = Publisher(self.task_start, transport=self.transport)
        self.task_completion_subscriber = Subscriber(self.task_completed, self.on_task_completed, transport=self.transport)
        self.task_completion_subscriber.subscribe()
        self.task_claim_subscriber = Subscriber(self.task_claim, self.on_task_claim, transport=self.transport)
        self.task_claim_subscriber.subscribe()
        self.task_allocation_publisher = Publisher(self.task_allocation, transport=self.transport)
        self.task_ack_publisher = Publisher(self.task_ack, transport=self.transport)

        # Session data is namespaced on BSID
        # but also most operations add blueprint ID to the key
        self.session_storage = SessionStorage(self.session.bsid)
        self.blueprint_storage = BlueprintStorage()

        existing_session = self.session_storage.load_session()
        if existing_session:
            self.session = existing_session
            LOG.info(f"Resuming session {self.session.bsid} with state {self.session.state}")
        else:
            self._preprocess_blueprint()
            self.session_storage.save_session(self.session)

        LOG.info(f"Initialized session storage for session BSID={self.session.bsid}")

        self._build_graph()
        self._scopes = ScopeRegistry(self.session, self.graph)
        self.scheduler = TaskScheduler(self.session, self.graph)

        self.register_instance(self)

    @property
    def state(self) -> BlueprintSessionState:
        return self.session.state

    @state.setter
    def state(self, value: BlueprintSessionState) -> None:
        self.session.state = value
        try:
            self.session_storage.save_session(self.session)
        except Exception as state_err:
            LOG.exception(f"failed to save session state to persistent storage. Error: {state_err}")

    @classmethod
    def register_instance(cls, instance: Orchestrator) -> None:
        """
        Registers an orchestrator instance and tracks active instances.
        """
        with cls._LOCK:
            cls._INSTANCES.append(instance)
            for inst in cls._INSTANCES[:]:
                if inst.state in (BlueprintSessionState.FAILED, BlueprintSessionState.COMPLETED):
                    # keep track only of active instances
                    cls._INSTANCES.remove(inst)

                if inst.state == BlueprintSessionState.RUNNING:
                    LOG.warning("Another orchestrator instance is already running in the background.")
                    # inst.stop()

    def _reset_failed_tasks(self) -> None:
        """Resets tasks that are in a non-resumable state to PENDING.

        Tasks in FAILED, RUNNING, or READY state are reset to PENDING so that
        they can be re-scheduled when the session resumes. Tasks that were RUNNING
        or READY at the time of a stop are no longer being worked on by any agent,
        so they need to be re-dispatched.
        """
        for node, data in self.graph.nodes(data=True):
            task: Task = data["task"]
            if task.state in (TaskState.FAILED, TaskState.RUNNING, TaskState.READY):
                LOG.debug(f"Resetting task {task.id} (state={task.state}) to PENDING")
                task.state = TaskState.PENDING

    def reset_task_state(self, blueprint_id: str, task_id: str, include_downstream: bool = True, clear_outputs: bool = True) -> list[str]:
        """Reset a task (and optionally its downstream dependents) to PENDING.

        Parameters
        ----------
        blueprint_id : str
            Blueprint ID of the task to reset.
        task_id : str
            Task ID to reset (within the blueprint).
        include_downstream : bool, optional
            If True, also reset tasks that depend on this task.
        clear_outputs : bool, optional
            If True, clear task outputs in session storage.

        Returns
        -------
        list[str]
            A list of fully-qualified task IDs that were reset.
        """
        if not self.graph:
            raise KeyError("Task graph is not initialized")

        fqn_task_id = f"{blueprint_id}.{task_id}"
        if fqn_task_id not in self.graph.node:
            raise KeyError(f"Task not found: {fqn_task_id}")

        to_reset = {fqn_task_id}
        if include_downstream:
            queue = [fqn_task_id]
            while queue:
                current = queue.pop()
                for neighbor in self.graph.neighbors_out(current):
                    if neighbor not in to_reset:
                        to_reset.add(neighbor)
                        queue.append(neighbor)

        LOG.info(f"Resetting {len(to_reset)} task(s) to PENDING: {sorted(to_reset)}")

        for fqn_id in to_reset:
            task: Task = self.graph.node[fqn_id]["task"]
            task_blueprint_id = self.graph.node[fqn_id]["blueprint_id"]
            task.state = TaskState.PENDING
            if clear_outputs:
                for output in task.outputs:
                    output.value = None
                    mapped_key = output.set_to or output.name
                    self.session_storage.set(task_blueprint_id, mapped_key, None)

        # If the session was in a terminal state (FAILED/COMPLETED), move it
        # back to STOPPED so that it can be resumed.
        if self.session.state in (BlueprintSessionState.FAILED, BlueprintSessionState.COMPLETED):
            LOG.info(f"Resetting session state from {self.session.state} to STOPPED after task reset.")
            self.session.state = BlueprintSessionState.STOPPED

        self.session_storage.save_session(self.session)
        return sorted(to_reset)

    def skip_task_state(self, blueprint_id: str, task_id: str) -> list[str]:
        """Skip a task and its inner blueprint tasks (if composite).

        For composite tasks, all tasks in the inner blueprint are also
        recursively skipped. Downstream dependent tasks are NOT skipped.

        Parameters
        ----------
        blueprint_id : str
            Blueprint ID of the task to skip.
        task_id : str
            Task ID to skip (within the blueprint).

        Returns
        -------
        list[str]
            A list of fully-qualified task IDs that were skipped.
        """
        if not self.graph:
            raise KeyError("Task graph is not initialized")

        fqn_task_id = f"{blueprint_id}.{task_id}"
        if fqn_task_id not in self.graph.node:
            raise KeyError(f"Task not found: {fqn_task_id}")

        skipped = [fqn_task_id]

        task: Task = self.graph.node[fqn_task_id]["task"]

        # If the task is pending, we don't set it to SKIPPED immediately, as that would
        # satisfy dependencies for downstream tasks prematurely. Instead, we mark it
        # to be skipped when it is scheduled.
        if task.state == TaskState.PENDING:
            task.state = TaskState.SKIP_REQUESTED
            LOG.info(f"Marked task {fqn_task_id} for skipping (state SKIP_REQUESTED)")

            # Recursively mark inner blueprint tasks for composite tasks
            if task.is_composite:
                inner_blueprint_id = self.session.composite_to_inner_blueprint_map.get(fqn_task_id)
                if inner_blueprint_id:
                    self._set_inner_blueprint_tasks_state(inner_blueprint_id, TaskState.SKIP_REQUESTED)

        self.session_storage.save_session(self.session)
        return skipped

    def get_currently_running_composite_blueprints(self) -> set[str]:
        blueprints = set()
        for node, data in self.graph.nodes(data=True):
            task: Task = data["task"]
            if task.state != TaskState.RUNNING:
                continue

            if task.is_dynamically_expanded:
                composite_options = task.get_param_value("blueprint")
                blueprint_id = composite_options["dynamic"]["blueprint_id"]
                LOG.debug(f"Found running task {task.id} in blueprint {blueprint_id}")
                blueprints.add(blueprint_id)

        return blueprints

    def start(self) -> None:
        """Starts the orchestrator."""
        if self.state == BlueprintSessionState.RUNNING:
            LOG.warning("Session is already running.")
            return

        self._reset_failed_tasks()
        self._completion_event.clear()

        # Ensure subscriptions are active (in case we are restarting after stop)
        self.task_completion_subscriber.subscribe()
        self.task_claim_subscriber.subscribe()

        self.state = BlueprintSessionState.RUNNING
        LOG.info(f"Orchestrator session with id {self.session.bsid} started!")
        self._schedule_tasks()

    def stop(self) -> None:
        """Stops the orchestrator."""
        self.task_completion_subscriber.unsubscribe()
        self.task_claim_subscriber.unsubscribe()

        # there might be pending completion messages in the scheduler queue of composite tasks
        # set them back to PENDING when orchestrator is stopped so that they can be processed when the session resumes.
        self._flush_scheduler_queue()

        if self.state == BlueprintSessionState.RUNNING:
            self.state = BlueprintSessionState.STOPPED
        LOG.info(f"Execution of session id {self.session.bsid} completed!")

    def pause(self) -> None:
        """Pauses the orchestrator."""
        self.state = BlueprintSessionState.STOPPED
        LOG.info(f"Orchestrator session with id {self.session.bsid} paused!")

    def await_completion(self, timeout: Optional[float] = None) -> bool:
        """Waits for the session to complete (succeed or fail).

        Parameters
        ----------
        timeout : float, optional
            The maximum time to wait in seconds.

        Returns
        -------
        bool
            True if the session completed, False if the timeout was reached.
        """
        return self._completion_event.wait(timeout)

    def _map_inputs_from_session(self, blueprint_id: str, task: Task) -> dict:
        """Resolve task inputs from session data applying argument remapping."""
        inputs = {}
        for inp in task.inputs:
            key = inp.name
            mapped_key = inp.get_from or key

            inputs_value = self.session_storage.get(blueprint_id, mapped_key)

            # Static inputs: If not found in session and map is implicit, use static value
            # This is to support things like the `test_orchestrator_composite` tests that
            # set static inputs directly in the programmatic definition of the task
            if inputs_value is None and not inp.get_from and inp.value is not None:
                inputs[key] = inp.value
                continue

            if task.is_dynamically_expanded:
                # in dynamically expanded tasks, the value is always a mapping {"element_id": "value"}
                # the aggregation happens in :meth:`_map_outputs_to_outer_session`
                if not isinstance(inputs_value, dict):
                    raise RuntimeError(f"Expected dict input for dynamically expanded task {task.id}, got {type(inputs_value)}. Data={inputs_value}")

                composite_options = task.get_param_value("blueprint")
                element_id = composite_options["dynamic"]["element"]["element_id"]

                if element_id not in inputs_value:
                    raise KeyError(
                        f"Expected aggregated input for element_id {element_id} in task {task.id}, "
                        f"but it was not found. Did you skip the task which should have produced this input?"
                    )
                inputs[key] = inputs_value[element_id]
            else:
                inputs[key] = inputs_value
        return inputs

    def _map_outputs_to_session(self, blueprint_id: str, task: Task) -> dict:
        """Map task outputs to the names used in session data."""
        outputs = {}
        # Iterate over output keys defined in the task configuration
        for out in task.outputs:
            # Get the configured mapping name or default to the key itself
            mapped_key = out.set_to or out.name
            outputs[mapped_key] = out.value

        # TODO: Should use set_all() here
        # I implemented set_all in SessionStorage but commented it out for now
        # because it throws a weird error:
        # UNKNOWN:Error received from peer ipv6:%5B::1%5D:3322 {grpc_status:2, grpc_message:"no entries provided"}
        # self.session_storage.set_all(blueprint_id, outputs)
        for k, v in outputs.items():
            self.session_storage.set(blueprint_id, k, v)

        return outputs

    def _map_outputs_to_outer_session(self, outer_blueprint_id: str, task: Task):
        """maps outputs from an inner blueprint to the session storage namespace of the outer blueprint."""
        inner_blueprint_id = self.session.composite_to_inner_blueprint_map[_create_global_id(outer_blueprint_id, task)]

        element = None
        if task.is_dynamically_expanded:
            composite_options = task.get_param_value("blueprint")
            element = composite_options["dynamic"]["element"]

        for out in task.outputs:
            mapped_key = out.set_to or out.name
            value = self.session_storage.get(inner_blueprint_id, out.name)

            if element:
                # If dynamic, we aggregate into a dictionary in the outer session
                element_id = element["element_id"]
                existing_value = self.session_storage.get(outer_blueprint_id, mapped_key) or {}
                existing_value[element_id] = value
                self.session_storage.set(outer_blueprint_id, mapped_key, existing_value)
            else:
                self.session_storage.set(outer_blueprint_id, mapped_key, value)

    def _add_composite_blueprint_context(self, blueprint_id: str, task: Task) -> None:
        # make context of composite tasks available to the tasks in the inner blueprint they invoke
        composite_options = task.get_param_value("blueprint")
        if not composite_options:
            raise RuntimeError(f"Tried to add composite context for task with missing blueprint options: {task.id}")
        fabrication_context = composite_options["dynamic"]["element"]
        self.session.blueprint_contexts[blueprint_id] = fabrication_context.copy()

    def get_composite_blueprint_context(self, blueprint_id: str) -> Optional[Dict]:
        return self.session.blueprint_contexts.get(blueprint_id)

    def _get_model_if_available(self) -> Tuple[Optional[Model], Any]:
        model_id = self.session.params.get("model_id")
        model: Optional[Model] = None
        nesting = None
        if model_id is not None:
            with ModelStorage() as storage:
                model = storage.get_model(model_id)
                nesting = storage.get_nesting(model_id)
        return model, nesting

    def _evaluate_skip_condition(self, task: Task, inputs: Dict[str, Any], blueprint_id: str) -> bool:
        """Determines if a task should be skipped based on conditions or parent states."""

        # 1. Explicit Condition Check
        condition = task.condition
        if not condition:
            # Backward compatibility check
            condition_param = task.get_param("condition")
            condition = condition_param.value if condition_param else None

        if condition:
            try:
                # context = self.get_composite_blueprint_context(blueprint_id) or {}
                composite_options = task.get_param_value("blueprint") or {}
                fabrication_context = composite_options.get("dynamic", {}).get("element", {})
                context = self.get_composite_blueprint_context(blueprint_id) or {}

                allowed_names = params_to_dict(task.params)
                allowed_names.update(inputs.copy())
                allowed_names.update(fabrication_context)
                allowed_names.update(context)

                # NOTE: by injecting the entire session data into the eval context we allow conditions
                # to reference anything from the blueprint's namespace. while handy, this might be too implicit
                # and cause confusion with regards to the data flow across tasks.
                # TODO: revisite this decision.
                session_data = self.session_storage.get_all(blueprint_id)
                allowed_names.update(session_data)

                LOG.debug(f"Evaluating condition for task {task.id} with context: {allowed_names}")

                if not safe_eval_condition(condition, allowed_names):
                    LOG.info(f"Task {task.id} skipped due to condition: {condition}")
                    return True
            except Exception as e:
                LOG.error(f"Error evaluating condition '{condition}' for task {task.id}: {e}")
                raise

        return False

    def _handle_skipped_task(self, task: Task, blueprint_id: str) -> None:
        """Handles the completion logic for a skipped task."""
        task.state = TaskState.SKIPPED
        fqn_task_id = _create_global_id(blueprint_id, task)

        # If this is a composite task, also skip all tasks in the inner blueprint
        # to prevent the scheduler from picking them up
        if task.is_composite:
            inner_blueprint_id = self.session.composite_to_inner_blueprint_map.get(fqn_task_id)
            if inner_blueprint_id:
                self._set_inner_blueprint_tasks_state(inner_blueprint_id, TaskState.SKIPPED)

        # If this is a scope_start task, cascade SKIPPED to all other tasks in the scope
        if task.scope_start is not None:
            scope = self._scopes.get(task.id)
            if scope:
                scope.skip_tasks(self.graph, excluded_fqn=fqn_task_id)

        completion_msg = TaskCompletionMessage(id=fqn_task_id, state=TaskState.SKIPPED, outputs={}, agent_id="system")

        self.on_task_completed(completion_msg)

    def _set_inner_blueprint_tasks_state(self, blueprint_id: str, target_state: TaskState) -> None:
        """Recursively sets the state of inner blueprint tasks.

        Parameters
        ----------
        blueprint_id : str
            The ID of the inner blueprint.
        target_state : TaskState
            The state to set (e.g., TaskState.SKIPPED or TaskState.SKIP_REQUESTED).
        """
        for node, data in self.graph.nodes(data=True):
            if data["blueprint_id"] != blueprint_id:
                continue
            inner_task: Task = data["task"]

            # Filter valid transitions to avoid overwriting finished tasks
            if inner_task.state in (TaskState.SUCCEEDED, TaskState.FAILED, TaskState.SKIPPED):
                continue

            if target_state == TaskState.SKIP_REQUESTED and inner_task.state != TaskState.PENDING:
                continue

            inner_task.state = target_state
            LOG.debug(f"Set task {inner_task.id} state to {target_state} (blueprint: {blueprint_id})")

            # Recursively handle nested inner blueprints
            if inner_task.is_composite:
                fqn_inner_task_id = _create_global_id(blueprint_id, inner_task)
                nested_blueprint_id = self.session.composite_to_inner_blueprint_map.get(fqn_inner_task_id)
                if nested_blueprint_id:
                    self._set_inner_blueprint_tasks_state(nested_blueprint_id, target_state)

    def _build_scope_registry(self) -> None:
        """Rebuild the scope registry from the current graph (e.g. after resume)."""
        self._scopes = ScopeRegistry(self.session, self.graph)

    def _handle_scope_completion(self, processed_task: ProcessedTask) -> bool:
        """Evaluate the scope loop policy when a scope_end task completes.

        Returns True if scope tasks were reset for another iteration, False otherwise.
        """
        task = processed_task.task
        if not task.scope_end:
            return False

        scope = self._scopes.get(task.scope_end)
        if scope is None:
            LOG.warning(f"Scope '{task.scope_end}' not found in registry; skipping policy evaluation.")
            return False

        iterations = self.session.scope_iterations.get(scope.name, 0)

        eval_context = self.session_storage.get_all(processed_task.blueprint_id)
        eval_context.update(self.get_composite_blueprint_context(processed_task.blueprint_id) or {})

        if not scope.should_loop(iterations, eval_context):
            return False

        self.session.scope_iterations[scope.name] = iterations + 1
        scope.reset_tasks(self.graph)
        LOG.info(f"Scope '{scope.name}': reset {len(scope.task_fqns)} tasks to PENDING for iteration {iterations + 2}.")
        return True

    def _schedule_tasks(self) -> None:
        """Schedules tasks for execution."""
        pending_tasks = self.scheduler.get_pending_tasks()

        LOG.debug(f"TICK: There are {len(pending_tasks)} pending tasks.")

        # NOTE: doing this here will fetch the model evey cycle.
        # NOTE: we could theoratically do this only once per session, unless we expect the model to change during execution..
        model, nesting = self._get_model_if_available()

        for pending_task in pending_tasks:
            try:
                blueprint_id = pending_task.blueprint_id
                task = pending_task.task

                LOG.debug(f"Processing pending task {task}")

                # Prepare inputs to pass to the task
                inputs = self._map_inputs_from_session(blueprint_id, task)

                if task.state == TaskState.SKIP_REQUESTED or self._evaluate_skip_condition(task, inputs, blueprint_id):
                    LOG.debug(f"Pending task [{task.id}] will be skipped.")
                    self._handle_skipped_task(task, blueprint_id)
                    continue

                # Handle inputs for inner blueprints
                if task.is_composite:
                    inner_blueprint_id = self.session.composite_to_inner_blueprint_map[_create_global_id(blueprint_id, task)]
                    # NOTE: See above for why set_all() is commented out
                    # self.session_storage.set_all(inner_blueprint_id, inputs)
                    for key, value in inputs.items():
                        self.session_storage.set(inner_blueprint_id, key, value)

                execution_mode = task.get_param_value("execution_mode", ExecutionMode.EXCLUSIVE)

                if model:
                    task.set_param_value("model", model)
                if nesting:
                    task.set_param_value("nesting", nesting)

                context = self.get_composite_blueprint_context(blueprint_id)

                # TODO: what do we do if no agent even claims the task.. should there be some timeout? YES!
                task.state = TaskState.READY
                LOG.debug(f"Publishing TaskAssignmentMessage for task [{task.id}]")
                message = TaskAssignmentMessage(
                    id=_create_global_id(blueprint_id, task),
                    type=task.type,
                    inputs=inputs,
                    output_keys=outputs_to_keys(task.outputs),
                    params=params_to_dict(task.params),
                    execution_mode=execution_mode,
                    context=context,
                )
                self.task_start_publisher.publish(message)
                LOG.debug("Published TaskAssignmentMessage...")
            except Exception as e:
                LOG.exception(f"Failed to start task [{task.id}]: {e}")
                task.state = TaskState.FAILED
                self.state = BlueprintSessionState.FAILED
                self._completion_event.set()

        # Persist the updated session state
        self.session_storage.save_session(self.session)

    def _get_last_task(self) -> Task:
        for node, data in self.graph.nodes(data=True):
            if self.graph.degree_out(node) == 0:
                return data["task"]

        raise AssertionError("Clearly something went horribly wrong, no last task found!")

    def _is_last_task_in_blueprint(self, processed_task: ProcessedTask) -> bool:
        last_task = self._get_last_task()
        last_task_fqn_id = _create_global_id(self.session.blueprint.id, last_task)
        fqn_task_id = _create_global_id(processed_task.blueprint_id, processed_task.task)
        return last_task_fqn_id == fqn_task_id

    def on_task_completed(self, message: TaskCompletionMessage) -> None:
        """Handles incoming task completion messages."""
        LOG.info(f"task completion received : {message}")

        self.scheduler.queue_message(message)
        processed_tasks = self.scheduler.process_queue()

        for processed_task in processed_tasks:
            LOG.debug(f"Task {processed_task.task_id} finished with state {processed_task.task.state}")

            blueprint_id = processed_task.blueprint_id

            # Handle outs from inner blueprints
            if processed_task.task.is_composite:
                self._map_outputs_to_outer_session(blueprint_id, processed_task.task)
            else:
                self._map_outputs_to_session(blueprint_id, processed_task.task)

            if processed_task.task.state == TaskState.FAILED:
                LOG.error(f"Task {processed_task.task_id} failed, aborting session.")
                self.state = BlueprintSessionState.FAILED
                self._completion_event.set()
                self.stop()
                return

            if self._is_last_task_in_blueprint(processed_task):
                self.state = BlueprintSessionState.COMPLETED
                self._completion_event.set()
                self.stop()

            # Handle scope loop policy (only for successfully completed tasks)
            if processed_task.task.state == TaskState.SUCCEEDED and self.state == BlueprintSessionState.RUNNING:
                self._handle_scope_completion(processed_task)

        # Send ACK
        ack = TaskCompletionAckMessage(id=message.id, state=TaskState(message.state), accepted_agent_id=message.agent_id)
        self.task_ack_publisher.publish(ack)

        # Persist the updated session state
        self.session_storage.save_session(self.session)

        if self.state == BlueprintSessionState.RUNNING:
            self._schedule_tasks()

    def on_task_claim(self, message: TaskClaimRequest) -> None:
        """Handles incoming task claim requests."""
        LOG.info(f"Task claim received: {message}")

        assert self.graph is not None

        task_id = message.task_id
        task = cast(Task, self.graph.node_attribute(task_id, "task"))
        if task is None:
            LOG.warning(f"Received claim for unknown task: {task_id}")
            return

        execution_mode = task.get_param_value("execution_mode", ExecutionMode.EXCLUSIVE)
        can_allocate = False
        if task.state == TaskState.READY:
            can_allocate = True
        elif task.state == TaskState.RUNNING and execution_mode == ExecutionMode.COMPETITIVE:
            can_allocate = True

        if can_allocate:
            task.state = TaskState.RUNNING

            allocation = TaskAllocationMessage(task_id=task_id, assigned_agent_id=message.agent_id)
            self.task_allocation_publisher.publish(allocation)
            LOG.info(f"Allocated task {task_id} to agent {message.agent_id} (Mode: {execution_mode})")

            # Persist the updated session state
            self.session_storage.save_session(self.session)
        else:
            LOG.info(f"Rejected claim for task {task_id} from agent {message.agent_id}. Task state is {task.state}")

    def _flush_scheduler_queue(self) -> None:
        # Drains the scheduler queue and resets pending tasks to PENDING state
        if not self.scheduler or self.scheduler.queue.empty():
            return

        LOG.info("Flushing scheduler queue tasks to PENDING state...")
        while not self.scheduler.queue.empty():
            try:
                # Non-blocking get to avoid deadlock
                message = self.scheduler.queue.get_nowait()
            except Empty:
                break
            fqn_task_id = message.id
            if fqn_task_id in self.graph.node:
                task = self.graph.node[fqn_task_id]["task"]
                # Only reset tasks that are currently marked as RUNNING
                # (meaning they finished execution but were waiting on dependencies in the queue)
                if task.state == TaskState.RUNNING:
                    LOG.debug(f"Resetting task {task.id} to PENDING for persistence.")
                    task.state = TaskState.PENDING

        self.session_storage.save_session(self.session)

    def _expand_dynamic_tasks(self, blueprint: Blueprint) -> None:
        expanded_something = True
        while expanded_something:
            expanded_something = False
            # Iterate over a copy of tasks to allow modification of the blueprint
            for task in list(blueprint.tasks):
                if task.is_dynamic and not task.is_dynamically_expanded:
                    blueprint_params = task.get_param_value("blueprint", {})
                    dynamic_params = blueprint_params.get("dynamic") or {}

                    sequencer_name = dynamic_params["sequencer"]
                    sequencer = SequencerRegistry.get_sequencer(sequencer_name, self.session)

                    blueprint = sequencer.expand(task, blueprint)
                    expanded_something = True
                    # Break to restart the loop with the modified blueprint
                    break

    def _preprocess_blueprint(self) -> None:
        """Preprocesses the blueprint before execution to expand composite tasks."""
        blueprint_queue = Queue()
        blueprint_queue.put(self.session.blueprint)

        while not blueprint_queue.empty():
            blueprint = blueprint_queue.get()

            self._expand_dynamic_tasks(blueprint)

            for task in blueprint.tasks:
                # Removed _init_session_data_for_task call as it is deprecated

                if task.is_composite:
                    LOG.debug(f"Loading inner blueprint for composite task {task.id} in blueprint {blueprint.id}")
                    inner_blueprint = self._load_inner_blueprint(task)
                    self.session.inner_blueprints[inner_blueprint.id] = inner_blueprint
                    blueprint_queue.put(inner_blueprint)

                    fqn_task_id = _create_global_id(blueprint.id, task)
                    self.session.composite_to_inner_blueprint_map[fqn_task_id] = inner_blueprint.id

                    if task.is_dynamic:
                        self._add_composite_blueprint_context(inner_blueprint.id, task)

        LOG.debug(f"expanded blueprint map: {self.session.composite_to_inner_blueprint_map}")

    def _load_inner_blueprint(self, task: Task) -> Blueprint:
        blueprint_param = task.get_param_value("blueprint")
        assert blueprint_param is not None

        if "static" in blueprint_param:
            blueprint_id = blueprint_param["static"]
            blueprint = self.blueprint_storage.get_blueprint(blueprint_id)
            # Create a unique instance per composite task to avoid ID collisions when
            # multiple tasks reference the same inner blueprint archetype.
            expanded_blueprint_id = f"{blueprint_id}_{task.id}"
            blueprint.id = expanded_blueprint_id
            return blueprint
        if "dynamic" in blueprint_param:
            # Get data from the expanded dynamic blueprint task data
            blueprint_id = blueprint_param["dynamic"]["blueprint_id"]
            element = blueprint_param["dynamic"]["element"]

            # The expanded ID is used to avoid ID collisions
            # because multiple elements are processed with the same base blueprint
            # but different instances of it
            # NOTE: concatenating blueprint ID, task ID isn't always unique enough. if different composite tasks
            # use the same inner blueprint due to collision the orchestrator will just hang..
            short_element_id = element["element_id"][:8]  # use only first 8 chars to avoid too long IDs
            expanded_blueprint_id = f"{blueprint_id}_{task.id}_{short_element_id}"

            blueprint = self.blueprint_storage.get_blueprint(blueprint_id)
            blueprint.id = expanded_blueprint_id

            # NOTE: this isn't needed per se, but it's useful for debugging/logging purposes
            blueprint_param["dynamic"]["blueprint_id"] = expanded_blueprint_id

            LOG.debug(f"Loaded dynamic inner blueprint with new ID {expanded_blueprint_id} for task {task.id}")

            return blueprint

        raise NotImplementedError("Inner blueprint should be defined either as static or dynamic.")

    def _build_graph(self) -> None:
        """Builds a dependency graph from the loaded blueprint."""
        if not self.session:
            return

        self.graph = Graph()

        all_blueprints = [self.session.blueprint]
        all_blueprints.extend(list(self.session.inner_blueprints.values()))

        dependencies_to_inject = []

        for blueprint in all_blueprints:
            for task in blueprint.tasks:
                fqn_task_id = _create_global_id(blueprint.id, task)

                if fqn_task_id in self.session.composite_to_inner_blueprint_map:
                    # 1. Modify `task` to point to inner blueprint's end node as FF
                    # 2. Modify start task of inner_blueprint, to have an SS dependency on THIS `task`
                    inner_blueprint_id = self.session.composite_to_inner_blueprint_map[fqn_task_id]
                    inner_blueprint = self.session.inner_blueprints[inner_blueprint_id]

                    # Find start/end task of inner blueprint
                    start_task = None
                    end_task = None
                    for t in inner_blueprint.tasks:
                        if t.is_start:
                            start_task = t
                        if t.is_end:
                            end_task = t
                        if start_task and end_task:
                            break

                    fqn_inner_end_task_id = _create_global_id(inner_blueprint_id, end_task)
                    fqn_inner_start_task_id = _create_global_id(inner_blueprint_id, start_task)

                    dependencies_to_inject.append((fqn_task_id, fqn_inner_end_task_id, DependencyType.FF))
                    dependencies_to_inject.append((fqn_inner_start_task_id, fqn_task_id, DependencyType.SS))

                self.graph.add_node(fqn_task_id, task=task, blueprint_id=blueprint.id)

            for task in blueprint.tasks:
                for dep in task.depends_on:
                    self.graph.add_edge(_create_global_id(blueprint.id, dep), _create_global_id(blueprint.id, task), type=dep.type)

            for from_task_id, to_task_id, dep_type in dependencies_to_inject:
                self.graph.add_edge(to_task_id, from_task_id, type=dep_type)

        # NOTE: Perhaps we need to do transitive_reduction here

    def to_mermaid_diagram(self, title="Blueprint") -> str:
        """Generate a mermaid-syntax diagram representation of the blueprint session.

        Returns
        -------
        str
            Gantt chart representation of the blueprint session.
        """
        return self.scheduler.to_mermaid_diagram(title)
