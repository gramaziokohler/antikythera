from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from enum import auto
from queue import LifoQueue
from queue import Queue
from typing import Optional
from typing import cast

from compas.datastructures import Graph
from compas_eve import Publisher
from compas_eve import Subscriber
from compas_eve import Topic
from compas_eve.codecs import ProtobufMessageCodec
from compas_eve.mqtt import MqttTransport
from compas_model.models import Model

from antikythera.compat import StrEnum
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

            if dep_task.state != TaskState.SUCCEEDED:
                all_ff_succeeded = False
                break
        return all_ff_succeeded

    def _process_message(self, message: TaskCompletionMessage, task: Task, blueprint_id: str) -> ProcessedTask:
        # THIS METHOD MUTATES `task`
        # updated the task state according to the reported state in the message
        # create and return a ProcessedTask object
        if message.state == TaskState.SUCCEEDED.value:
            task.state = TaskState.SUCCEEDED
        elif message.state == TaskState.FAILED.value:
            task.state = TaskState.FAILED
        else:
            raise ValueError(f"Invalid task state: {message.state}")

        if task.outputs:
            task.outputs = message.outputs
        else:
            task.outputs = {}
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
            if task.state != TaskState.PENDING:
                continue

            dependencies = self._get_dependencies_from_graph(blueprint_id, task)
            dependency_preconditions = []

            for dep in dependencies:
                dep_task = self.graph.node[dep.id]["task"]
                dependency_type = dep.type

                if dependency_type == DependencyType.FS:
                    dependency_preconditions.append(dep_task.state == TaskState.SUCCEEDED)
                elif dependency_type == DependencyType.SS:
                    dependency_preconditions.append(dep_task.state in (TaskState.RUNNING, TaskState.SUCCEEDED))
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
                dependencies = datetime.date.today().isoformat()

            result.append("  {:40}   : {}{}, {}, {}".format(task_label, milestone, self._create_mermaid_task_id(blueprint_id, task), dependencies, duration))

        root_node = None
        for node in self.graph.nodes():
            if self.graph.degree_in(node) == 0:
                root_node = node
                append_node(None, root_node)
                break

        breadth_first_traverse(self.graph.adjacency, root_node, append_node)

        return "\n".join(result)


class OrchestratorState(StrEnum):
    IDLE = auto()
    RUNNING = auto()
    PAUSED = auto()
    FINISHED = auto()


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

    def __init__(self, session: BlueprintSession, broker_host="127.0.0.1", broker_port=1883) -> None:
        super(Orchestrator, self).__init__()
        self.session: BlueprintSession = session
        self.composite_to_inner_blueprint_map: dict[str, str] = {}
        self.graph: Graph = None
        self._state = OrchestratorState.IDLE
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

        existing_session = self.session_storage.get_session_info()
        if existing_session:
            self.session.state = BlueprintSessionState(existing_session["state"])
            LOG.info(f"Resuming session {self.session.bsid} with state {self.session.state}")
        else:
            self.session_storage.register_session(self.session.blueprint.id, self.session.params, state=self.session.state)

        self.blueprint_storage = BlueprintStorage()
        LOG.info(f"Initialized session storage for session BSID={self.session.bsid}")

        self._preprocess_blueprint()
        self._build_graph()
        self.scheduler = TaskScheduler(self.session, self.graph)

        self.register_instance(self)

    @classmethod
    def register_instance(cls, instance: Orchestrator) -> None:
        # NOTE: this is a speculative change as I think we might need to keep track of multiple orchestrator
        # instances and, potentially, not allow multiple running at the same time. due to the event-diriven nature
        # multiple running orchestrators is a pain.
        cls._INSTANCES.append(instance)
        for inst in cls._INSTANCES:
            if inst._state == OrchestratorState.FINISHED:
                # keep track only of active instances
                cls._INSTANCES.remove(inst)

            if inst._state == OrchestratorState.RUNNING:
                LOG.warning("Another orchestrator instance is already running in the background.")
                # TODO: kill it? should we allow multiple instances? Probably not..
                # inst.stop()

    def _reset_failed_tasks(self) -> None:
        """Resets tasks that are in FAILED state to PENDING."""
        for node, data in self.graph.nodes(data=True):
            task: Task = data["task"]
            if task.state == TaskState.FAILED:
                LOG.debug(f"Resetting failed task {task.id} to PENDING")
                task.state = TaskState.PENDING

    def start(self) -> None:
        """Starts the orchestrator."""
        if self._state == OrchestratorState.RUNNING:
            LOG.warning("Orchestrator is already running.")
            return

        self._reset_failed_tasks()
        self._completion_event.clear()

        # Ensure subscriptions are active (in case we are restarting after stop)
        self.task_completion_subscriber.subscribe()
        self.task_claim_subscriber.subscribe()

        self.session.state = BlueprintSessionState.RUNNING
        self.session_storage.update_session_state(self.session.state)
        LOG.info(f"Orchestrator session with id {self.session.bsid} started!")
        self._state = OrchestratorState.RUNNING
        self._schedule_tasks()

    def stop(self) -> None:
        """Stops the orchestrator."""
        self._state = OrchestratorState.FINISHED
        self.task_completion_subscriber.unsubscribe()
        self.task_claim_subscriber.unsubscribe()
        # NOTE: for now don't close session storage until we figure out how to better handle it on the API
        # try:
        #     self.session_storage.close()
        # except Exception as exc:
        #     LOG.error(f"Error closing session storage: {exc}")
        if self.session.state == BlueprintSessionState.RUNNING:
            self.session.state = BlueprintSessionState.STOPPED
            self.session_storage.update_session_state(self.session.state)
        LOG.info(f"Execution of session id {self.session.bsid} completed!")

    def pause(self) -> None:
        """Pauses the orchestrator."""
        self._state = OrchestratorState.PAUSED
        self.session.state = BlueprintSessionState.STOPPED
        self.session_storage.update_session_state(self.session.state)
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
        input_mapping = task.argument_mapping.get("inputs", {}) if task.argument_mapping else {}

        inputs = {}
        for key in task.inputs:
            mapped_key = input_mapping.get(key) or key
            inputs_value = self.session_storage.get(blueprint_id, mapped_key)

            if task.is_dynamically_expanded:
                # in dynamically expanded tasks, the value is always a mapping {"element_id": "value"}
                # the aggregation happens in :meth:`_map_outputs_to_outer_session`
                assert isinstance(inputs_value, dict)
                element_id = task.try_get_element_id()
                inputs[key] = inputs_value[element_id]
            else:
                inputs[key] = inputs_value
        return inputs

    def _map_outputs_to_session(self, blueprint_id: str, task: Task) -> dict:
        """Map task outputs to the names used in session data."""
        output_mapping = task.argument_mapping.get("outputs", {}) if task.argument_mapping else {}
        task_outputs = task.outputs or {}

        outputs = {}
        for key, value in task_outputs.items():
            mapped_key = output_mapping.get(key) or key
            outputs[mapped_key] = value

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
        inner_blueprint_id = self.composite_to_inner_blueprint_map[_create_global_id(outer_blueprint_id, task)]

        element = None
        if task.is_dynamically_expanded:
            element = self.session_storage.get(inner_blueprint_id, "element")

        for key in task.outputs:
            mapped_key = task.argument_mapping.get("outputs", {}).get(key) or key
            value = self.session_storage.get(inner_blueprint_id, key)

            if element:
                # If dynamic, we aggregate into a dictionary in the outer session
                element_id = element["element_id"]
                existing_value = self.session_storage.get(outer_blueprint_id, mapped_key) or {}
                existing_value[element_id] = value
                self.session_storage.set(outer_blueprint_id, mapped_key, existing_value)
            else:
                self.session_storage.set(outer_blueprint_id, mapped_key, value)

    def _get_model_if_available(self) -> Optional[Model]:
        model_id = self.session.params.get("model_id")
        model: Optional[Model] = None
        if model_id is not None:
            with ModelStorage() as storage:
                model = storage.get_model(model_id)
        return model

    def _schedule_tasks(self) -> None:
        """Schedules tasks for execution."""
        pending_tasks = self.scheduler.get_pending_tasks()

        # NOTE: doing this here will fetch the model evey cycle.
        # NOTE: we could theoratically do this only once per session, unless we expect the model to change during execution..
        model = self._get_model_if_available()

        for pending_task in pending_tasks:
            try:
                blueprint_id = pending_task.blueprint_id
                task = pending_task.task

                task.state = TaskState.PENDING

                # Prepare inputs to pass to the task
                inputs = self._map_inputs_from_session(blueprint_id, task)

                # Handle inputs for inner blueprints
                if task.is_composite:
                    inner_blueprint_id = self.composite_to_inner_blueprint_map[_create_global_id(blueprint_id, task)]
                    # NOTE: See above for why set_all() is commented out
                    # self.session_storage.set_all(inner_blueprint_id, inputs)
                    for key, value in inputs.items():
                        self.session_storage.set(inner_blueprint_id, key, value)

                # TODO: Implement other execution modes (execution mode should probably be defined in the blueprint?)
                execution_mode = task.params.get("execution_mode", ExecutionMode.EXCLUSIVE)

                if model:
                    task.params["model"] = model

                # TODO: what do we do if no agent even claims the task.. should there be some timeout?
                task.state = TaskState.READY
                self.task_start_publisher.publish(
                    TaskAssignmentMessage(
                        id=_create_global_id(blueprint_id, task),
                        type=task.type,
                        inputs=inputs,
                        output_keys=task.outputs,
                        params=task.params,
                        execution_mode=execution_mode,
                    )
                )
            except Exception as e:
                LOG.exception(f"Failed to start task {task.id}: {e}")
                task.state = TaskState.FAILED
                self.session.state = BlueprintSessionState.FAILED
                self.session_storage.update_session_state(self.session.state)
                self._completion_event.set()

        # Persist the updated blueprint state (with task states)
        self.session_storage.update_session_blueprint_state(self.session.blueprint)

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
                self.session.state = BlueprintSessionState.FAILED
                self.session_storage.update_session_state(self.session.state)
                self._completion_event.set()
                self.stop()
                return

            if self._is_last_task_in_blueprint(processed_task):
                self.session.state = BlueprintSessionState.COMPLETED
                self.session_storage.update_session_state(self.session.state)
                self.session_storage.update_session_ended()
                self._completion_event.set()
                self.stop()

        # Send ACK
        ack = TaskCompletionAckMessage(id=message.id, state=TaskState(message.state), accepted_agent_id=message.agent_id)
        self.task_ack_publisher.publish(ack)

        # Persist the updated blueprint state (with task states)
        self.session_storage.update_session_blueprint_state(self.session.blueprint)

        if self._state == OrchestratorState.RUNNING:
            self._schedule_tasks()

    def on_task_claim(self, message: TaskClaimRequest) -> None:
        """Handles incoming task claim requests."""
        LOG.info(f"Task claim received: {message}")

        assert self.graph is not None

        task_id = message.task_id
        task = cast(Task, self.graph.node_attribute(task_id, "task"))
        if task_id is None:
            LOG.warning(f"Received claim for unknown task: {task_id}")
            return

        if task.state == TaskState.READY:
            task.state = TaskState.RUNNING

            allocation = TaskAllocationMessage(task_id=task_id, assigned_agent_id=message.agent_id)
            self.task_allocation_publisher.publish(allocation)
            LOG.info(f"Allocated task {task_id} to agent {message.agent_id}")

            # Persist the updated blueprint state (with task states)
            self.session_storage.update_session_blueprint_state(self.session.blueprint)
        else:
            LOG.info(f"Rejected claim for task {task_id} from agent {message.agent_id}. Task state is {task.state}")

    def _init_session_data_for_task(self, blueprint_id: str, task: Task) -> None:
        # some tasks my have inputs that are static, serialized data values
        # put those into session data before execution starts
        for key, value in task.inputs.items():
            # NOTE: this is problematic for the situations in which you actually want to have strings as the actual value
            if not isinstance(value, str):
                self.session_storage.set(blueprint_id, key, value)

    def _expand_dynamic_tasks(self, blueprint: Blueprint) -> None:
        expanded_something = True
        while expanded_something:
            expanded_something = False
            # Iterate over a copy of tasks to allow modification of the blueprint
            for task in list(blueprint.tasks):
                if task.is_dynamic and not task.is_dynamically_expanded:
                    blueprint_params = task.params.get("blueprint") or {}
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
                self._init_session_data_for_task(blueprint.id, task)

                if task.is_composite:
                    LOG.debug(f"Loading inner blueprint for composite task {task.id} in blueprint {blueprint.id}")
                    inner_blueprint = self._load_inner_blueprint(task)
                    self.session.inner_blueprints[inner_blueprint.id] = inner_blueprint
                    blueprint_queue.put(inner_blueprint)

                    fqn_task_id = _create_global_id(blueprint.id, task)
                    self.composite_to_inner_blueprint_map[fqn_task_id] = inner_blueprint.id

        # Update session storage with inner blueprint IDs
        self.session_storage.update_session_blueprints(list(self.session.inner_blueprints.keys()))
        # Update session storage with the expanded blueprint
        self.session_storage.update_session_blueprint_state(self.session.blueprint)

        # store session blueprints
        # these are session specific copies of the blueprints, they may have been modified during preprocessing
        # e.g. dynamic tasks expanded, new blueprints created etc.
        self.session_storage.store_blueprint(self.session.blueprint)
        for inner_blueprint in self.session.inner_blueprints.values():
            self.session_storage.store_blueprint(inner_blueprint)

        # json_dump(self.session, f"orchestrator_preprocessed_session_{self.session.bsid}.json")

    def _load_inner_blueprint(self, task: Task) -> Blueprint:
        assert "blueprint" in task.params

        if "static" in task.params["blueprint"]:
            blueprint_id = task.params["blueprint"]["static"]
            return self.blueprint_storage.get_blueprint(blueprint_id)
        if "dynamic" in task.params["blueprint"]:
            # Get data from the expanded dynamic blueprint task data
            blueprint_id = task.params["blueprint"]["dynamic"]["blueprint_id"]
            element = task.params["blueprint"]["dynamic"]["element"]

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
            task.params["blueprint"]["dynamic"]["blueprint_id"] = expanded_blueprint_id

            LOG.debug(f"Loaded dynamic inner blueprint with new ID {expanded_blueprint_id} for task {task.id}")

            # We need to store an input param into the expanded blueprint to pass on the element details
            self.session_storage.set(expanded_blueprint_id, "element", element)

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

                if fqn_task_id in self.composite_to_inner_blueprint_map:
                    # 1. Modify `task` to point to inner blueprint's end node as FF
                    # 2. Modify start task of inner_blueprint, to have an SS dependency on THIS `task`
                    inner_blueprint_id = self.composite_to_inner_blueprint_map[fqn_task_id]
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
