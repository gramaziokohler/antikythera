from __future__ import annotations

import logging
import threading
import time
from typing import Iterable
from typing import Optional

import coolname
from compas_eve import Publisher
from compas_eve import Subscriber
from compas_eve import Topic
from compas_eve import Transport
from compas_eve.codecs import ProtobufMessageCodec

from antikythera.models import Task
from antikythera.models import TaskAllocationMessage
from antikythera.models import TaskAssignmentMessage
from antikythera.models import TaskClaimRequest
from antikythera.models import TaskCompletionAckMessage
from antikythera.models import TaskCompletionMessage
from antikythera.models import TaskError
from antikythera.models import TaskState
from antikythera.models.conversions import dict_to_inputs
from antikythera.models.conversions import dict_to_params
from antikythera.models.conversions import keys_to_outputs
from antikythera.transport import check_transport
from antikythera.transport import create_transport
from antikythera_actors.cli import Colors
from antikythera_actors.context import ExecutionContext
from antikythera_actors.descriptor import ToolBindingError

THREAD_JOIN_TIMEOUT = 10

LOG = logging.getLogger(__name__)


def _get_eve_transport(host, port, codec, transport, tls):
    return create_transport(broker_host=host, broker_port=port, mqtt_transport=transport, tls=tls)


def _ensure_actors():
    _get_plugin_manager().discover_plugins()


def _get_plugin_manager():
    from antikythera.plugin import PLUGIN_MANAGER

    return PLUGIN_MANAGER


class ActorLauncher:
    """Subscribes to the MQTT task bus, claims tasks on behalf of registered actors, and
    executes them in background threads.

    Each launcher instance is assigned a unique ID.  When the orchestrator broadcasts a
    new task assignment, all running launchers compete to claim it; the orchestrator picks
    one winner and broadcasts an allocation message.  Only the winning launcher executes
    the task; any others that started work cancel themselves on receipt of the ACK.

    Parameters
    ----------
    broker_host : str, optional
        Host of the MQTT broker. Ignored when ``transport`` is given.
    broker_port : int, optional
        Port of the MQTT broker. Ignored when ``transport`` is given.
    sys_only : bool, optional
        Only run the system actors.
    mqtt_transport : str, optional
        The MQTT socket transport, ``"tcp"`` or ``"websockets"``. Ignored when ``transport`` is given.
    tls : bool, optional
        Connect to the MQTT broker over TLS. Ignored when ``transport`` is given.
    actor_types : iterable of str, optional
        Only run the actors of these types. Defaults to every registered actor. Raises
        ``ValueError`` if one of them is not registered.
    discover : bool, optional
        Discover actors installed as plugins (the ``antikythera.actors`` entry point group)
        before starting. Turn it off to run only actors already imported, for example
        the ones defined in the running script.
    transport : compas_eve.Transport, optional
        The transport to exchange messages with the orchestrator over. It must use
        ``ProtobufMessageCodec``. For example a
        ``compas_eve.memory.InMemoryTransport`` shared with an orchestrator in the same
        process. Defaults to the transport configured by ``ANTIKYTHERA_TRANSPORT``: MQTT on
        ``broker_host``:``broker_port``, or NATS at ``NATS_URL``.
    """

    def __init__(
        self,
        broker_host: str = "127.0.0.1",
        broker_port: int = 1883,
        sys_only: bool = False,
        mqtt_transport: str = "tcp",
        tls: bool = False,
        *,
        actor_types: Optional[Iterable[str]] = None,
        discover: bool = True,
        transport: Optional[Transport] = None,
    ):
        self.launcher_id = coolname.generate_slug(4)
        self.sys_only = sys_only
        self.actor_types = None if actor_types is None else set(actor_types)
        self.discover = discover
        self.pending_claims = {}  # task_id -> Task
        self.active_contexts = {}  # task_id -> ExecutionContext

        self.threads = []
        self.thread_lock = threading.Lock()
        if transport is not None:
            self.transport = check_transport(transport)
        else:
            self.transport = _get_eve_transport(host=broker_host, port=broker_port, codec=ProtobufMessageCodec(), transport=mqtt_transport, tls=tls)
        self.task_start_subscriber = Subscriber(Topic("antikythera/task/start"), self.on_task_start, transport=self.transport)
        self.task_completion_publisher = Publisher(Topic("antikythera/task/completed"), transport=self.transport)
        self.task_claim_publisher = Publisher(Topic("antikythera/task/claim"), transport=self.transport)
        self.task_allocation_subscriber = Subscriber(Topic("antikythera/task/allocation"), self.on_task_allocation, transport=self.transport)
        self.task_ack_subscriber = Subscriber(Topic("antikythera/task/ack"), self.on_task_ack, transport=self.transport)

        self.actors = {}
        self._initialize_actors()
        LOG.info(f"Actor Launcher initialized with ID: {Colors.HEADER}{self.launcher_id}{Colors.ENDC}")

    def start(self):
        """Subscribe to all MQTT topics and begin accepting tasks."""
        self.task_start_subscriber.subscribe()
        self.task_allocation_subscriber.subscribe()
        self.task_ack_subscriber.subscribe()

    def stop(self):
        """Unsubscribe from MQTT topics, wait for in-flight tasks to finish, and dispose
        of all actor instances.
        """
        self.task_start_subscriber.unsubscribe()
        self.task_allocation_subscriber.unsubscribe()
        self.task_ack_subscriber.unsubscribe()

        with self.thread_lock:
            active_threads = list(self.threads)
            thread_count = len(active_threads)

        if thread_count > 0:
            LOG.info(f"Waiting for {thread_count} running tasks to complete...")

        deadline = time.time() + THREAD_JOIN_TIMEOUT

        for thread in active_threads:
            remaining_time = max(0, deadline - time.time())
            if remaining_time == 0 and thread.is_alive():
                LOG.info(f"Timeout reached, skipping join for {thread.name}")
                continue

            try:
                thread.join(remaining_time)
            except Exception as e:
                LOG.error(f"Error joining thread: {e}, continuing shutdown.")

        # Dispose of all actors
        for actor in self.actors.values():
            try:
                actor.dispose()
            except Exception as e:
                LOG.error(f"Error disposing actor: {e}")

    def _initialize_actors(self):
        from antikythera_actors.decorators import list_registered_actors

        if self.discover:
            _ensure_actors()

        registered_actors = list_registered_actors()
        if self.sys_only:
            registered_actors = {k: v for k, v in registered_actors.items() if k == "system"}
            LOG.info(f"{Colors.WARNING}--sys-only: restricting to system actors only.{Colors.ENDC}")
        if self.actor_types is not None:
            missing = self.actor_types - set(registered_actors)
            if missing:
                available = ", ".join(sorted(registered_actors)) or "none"
                raise ValueError(f"Unknown actor type(s): {', '.join(sorted(missing))}. Registered: {available}.")
            registered_actors = {k: v for k, v in registered_actors.items() if k in self.actor_types}
        for actor_type, actor_class in registered_actors.items():
            self.actors[actor_type] = actor_class()
            LOG.info(f"Initialized {actor_class.__name__} for type '{actor_type}' with {len(self.actors[actor_type].list_tools())} tools.")

        LOG.info(f"Total actors initialized: {len(self.actors)}")

    def on_task_start(self, message: TaskAssignmentMessage) -> None:
        """Handle an incoming task assignment broadcast.

        If a registered actor can handle the task type, the launcher publishes a claim
        request so the orchestrator can allocate it.
        """
        # Reconstruct valid Task object from assignment message

        inputs = dict_to_inputs(message.inputs)
        outputs = keys_to_outputs(message.output_keys)
        params = dict_to_params(message.params) if message.params else []

        task = Task(
            id=message.id,
            type=message.type,
            inputs=inputs,
            outputs=outputs,
            params=params,
            context=message.context,
        )

        # A task of type "<actor type>.<tool>" is only for actors of that type, even if an
        # actor of another type happens to have a tool with the same name.
        task_actor_type = task.type.rpartition(".")[0]
        for actor_type, actor in self.actors.items():
            if task_actor_type and actor_type != task_actor_type:
                continue
            if actor.can_claim_task(task):
                # We have an actor for this task, claim it!
                self.pending_claims[task.id] = (task, actor_type)
                claim = TaskClaimRequest(task_id=task.id, actor_id=self.launcher_id)
                self.task_claim_publisher.publish(claim)
                # Assuming only one actor per launcher claims it
                break

    def on_task_allocation(self, message: TaskAllocationMessage) -> None:
        """Handle a task allocation decision from the orchestrator.

        If this launcher was selected as the winner, the claimed task is dispatched to a
        background thread for execution.
        """
        if message.assigned_actor_id == self.launcher_id:
            task_id = message.task_id
            claim_info = self.pending_claims.pop(task_id, None)
            if claim_info:
                task, actor_type = claim_info
                thread = threading.Thread(target=self._execute_task_wrapper, daemon=True, args=(task, actor_type))
                with self.thread_lock:
                    self.threads.append(thread)
                thread.start()
            else:
                LOG.debug(f"Received allocation for unknown or already processed task {task_id}")

    def _execute_task_wrapper(self, task: Task, actor_type: str) -> None:
        # Create execution context
        context = ExecutionContext()
        with self.thread_lock:
            self.active_contexts[task.id] = context

        try:
            self._execute_task(task, actor_type, context)
        except Exception as ex:
            # actor task executino is protected, so an error here has to do with launcher code which may
            # lead to Orchestrator waiting indefinitely for completion message that will never arrive.
            self._handle_launcher_error_during_execution(task.id, ex)
        finally:
            with self.thread_lock:
                self.active_contexts.pop(task.id, None)
                self.threads.remove(threading.current_thread())

    def _handle_launcher_error_during_execution(self, task_id: str, exception: Exception):
        LOG.debug(f"{Colors.FAIL}❌ [{task_id}] Launcher Error: {exception}{Colors.ENDC}")
        error = TaskError(code="LAUNCHER_FAILURE", message="An error occurred in the actor launcher during task execution.", details=str(exception))
        failure_msg = TaskCompletionMessage(id=task_id, state=TaskState.FAILED, outputs={}, actor_id=self.launcher_id, error=error)
        self.task_completion_publisher.publish(failure_msg)

    def _execute_task(self, task: Task, actor_type: str, context: ExecutionContext) -> None:
        actor = self.actors.get(actor_type)

        if not actor:
            LOG.debug(f"{Colors.WARNING}⚠️  [WARNING] No actor found for task type: {task.type}{Colors.ENDC}")
            return

        outputs = {}
        error = None
        try:
            outputs = actor.execute_task(task, context=context)
            if not isinstance(outputs, dict):
                raise ValueError(f"Actor tools must return a dict of outputs. Got {type(outputs)} instead.")
            state = TaskState.SUCCEEDED
        except ToolBindingError as e:
            LOG.debug(f"{Colors.FAIL}❌ [{task.id}][{task.type}] Binding Error: {e}{Colors.ENDC}")
            state = TaskState.FAILED
            error = TaskError(code="TOOL_BINDING_ERROR", message=str(e), details=str(e))
        except Exception as e:
            if context.is_cancelled:
                # If cancelled, we log and return, without trying to set state, or outputs
                # or sending completion messages
                LOG.debug(f"{Colors.WARNING}🛑 [{task.id}][{task.type}] Task cancelled.{Colors.ENDC}")
                return

            LOG.debug(f"{Colors.FAIL}❌ [{task.id}][{task.type}] Actor Error: {e}{Colors.ENDC}")
            state = TaskState.FAILED
            error = TaskError(code="TOOL_FAILURE", message="The tool failed to complete its task. Bad tool.", details=str(e))

        msg = TaskCompletionMessage(id=task.id, state=state, outputs=outputs, actor_id=self.launcher_id, error=error)
        self.task_completion_publisher.publish(msg)

    def on_task_ack(self, message: TaskCompletionAckMessage) -> None:
        """Handle a task completion acknowledgement from the orchestrator.

        If another launcher was accepted for the same task and this launcher is still
        executing it, the local execution context is cancelled.
        """
        if message.accepted_actor_id != self.launcher_id:
            with self.thread_lock:
                context = self.active_contexts.get(message.id)

            if context:
                # It's a running task, and we are not the winner.
                LOG.debug(f"{Colors.WARNING}📉 [{message.id}] received ACK for {message.accepted_actor_id}, cancelling local execution.{Colors.ENDC}")
                context.cancel()

    def reload_actors(self):
        """Dispose of all current actor instances, reload plugins, and re-initialise actors.

        Useful for picking up newly installed actor packages without restarting the process.
        """
        LOG.debug(f"{Colors.OKBLUE}Reloading actors...{Colors.ENDC}")

        # Dispose of existing actors before reloading
        for actor in self.actors.values():
            try:
                actor.dispose()
            except Exception as e:
                LOG.debug(f"Error disposing actor during reload: {e}")

        _get_plugin_manager().reload_plugins()
        self._initialize_actors()
