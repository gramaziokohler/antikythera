from __future__ import annotations

import logging
import threading
import time

import coolname
from compas_eve import Publisher
from compas_eve import Subscriber
from compas_eve import Topic
from compas_eve.codecs import ProtobufMessageCodec
from compas_eve.mqtt import MqttTransport

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
from antikythera_agents.cli import Colors
from antikythera_agents.context import ExecutionContext

THREAD_JOIN_TIMEOUT = 10

LOG = logging.getLogger(__name__)


def _get_eve_transport(host, port, codec):
    return MqttTransport(host=host, port=port, codec=codec)


def _ensure_agents():
    _get_plugin_manager().discover_plugins()


def _get_plugin_manager():
    from antikythera.plugin import PLUGIN_MANAGER

    return PLUGIN_MANAGER


class AgentLauncher:
    def __init__(self, broker_host="127.0.0.1", broker_port=1883, sys_only=False):
        self.launcher_id = coolname.generate_slug(4)
        self.sys_only = sys_only
        self.pending_claims = {}  # task_id -> Task
        self.active_contexts = {}  # task_id -> ExecutionContext

        self.threads = []
        self.thread_lock = threading.Lock()
        self.transport = _get_eve_transport(host=broker_host, port=broker_port, codec=ProtobufMessageCodec())
        self.task_start_subscriber = Subscriber(Topic("antikythera/task/start"), self.on_task_start, transport=self.transport)
        self.task_completion_publisher = Publisher(Topic("antikythera/task/completed"), transport=self.transport)
        self.task_claim_publisher = Publisher(Topic("antikythera/task/claim"), transport=self.transport)
        self.task_allocation_subscriber = Subscriber(Topic("antikythera/task/allocation"), self.on_task_allocation, transport=self.transport)
        self.task_ack_subscriber = Subscriber(Topic("antikythera/task/ack"), self.on_task_ack, transport=self.transport)

        self.agents = {}
        self._initialize_agents()
        LOG.info(f"Agent Launcher initialized with ID: {Colors.HEADER}{self.launcher_id}{Colors.ENDC}")

    def start(self):
        self.task_start_subscriber.subscribe()
        self.task_allocation_subscriber.subscribe()
        self.task_ack_subscriber.subscribe()

    def stop(self):
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

        # Dispose of all agents
        for agent in self.agents.values():
            try:
                agent.dispose()
            except Exception as e:
                LOG.error(f"Error disposing agent: {e}")

    def _initialize_agents(self):
        from antikythera_agents.decorators import list_registered_agents

        _ensure_agents()

        registered_agents = list_registered_agents()
        if self.sys_only:
            registered_agents = {k: v for k, v in registered_agents.items() if k == "system"}
            LOG.info(f"{Colors.WARNING}--sys-only: restricting to system agents only.{Colors.ENDC}")
        for agent_type, agent_class in registered_agents.items():
            self.agents[agent_type] = agent_class()
            LOG.info(f"Initialized {agent_class.__name__} for type '{agent_type}' with {len(self.agents[agent_type].list_tools())} tools.")

        LOG.info(f"Total agents initialized: {len(self.agents)}")

    def on_task_start(self, message: TaskAssignmentMessage) -> None:
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

        for agent_type, agent in self.agents.items():
            if agent.can_claim_task(task):
                # We have an agent for this task, claim it!
                self.pending_claims[task.id] = (task, agent_type)
                claim = TaskClaimRequest(task_id=task.id, agent_id=self.launcher_id)
                self.task_claim_publisher.publish(claim)
                # Assuming only one agent per launcher claims it
                break

    def on_task_allocation(self, message: TaskAllocationMessage) -> None:
        if message.assigned_agent_id == self.launcher_id:
            task_id = message.task_id
            claim_info = self.pending_claims.pop(task_id, None)
            if claim_info:
                task, agent_type = claim_info
                thread = threading.Thread(target=self._execute_task_wrapper, daemon=True, args=(task, agent_type))
                with self.thread_lock:
                    self.threads.append(thread)
                thread.start()
            else:
                LOG.debug(f"Received allocation for unknown or already processed task {task_id}")

    def _execute_task_wrapper(self, task: Task, agent_type: str) -> None:
        # Create execution context
        context = ExecutionContext()
        with self.thread_lock:
            self.active_contexts[task.id] = context

        try:
            self._execute_task(task, agent_type, context)
        except Exception as ex:
            # agent task executino is protected, so an error here has to do with launcher code which may
            # lead to Orchestrator waiting indefinitely for completion message that will never arrive.
            self._handle_launcher_error_during_execution(task.id, ex)
        finally:
            with self.thread_lock:
                self.active_contexts.pop(task.id, None)
                self.threads.remove(threading.current_thread())

    def _handle_launcher_error_during_execution(self, task_id: str, exception: Exception):
        LOG.debug(f"{Colors.FAIL}❌ [{task_id}] Launcher Error: {exception}{Colors.ENDC}")
        error = TaskError(code="LAUNCHER_FAILURE", message="An error occurred in the agent launcher during task execution.", details=str(exception))
        failure_msg = TaskCompletionMessage(id=task_id, state=TaskState.FAILED, outputs={}, agent_id=self.launcher_id, error=error)
        self.task_completion_publisher.publish(failure_msg)

    def _execute_task(self, task: Task, agent_type: str, context: ExecutionContext) -> None:
        agent = self.agents.get(agent_type)

        if not agent:
            LOG.debug(f"{Colors.WARNING}⚠️  [WARNING] No agent found for task type: {task.type}{Colors.ENDC}")
            return

        try:
            outputs = agent.execute_task(task, context=context)
            if not isinstance(outputs, dict):
                raise ValueError(f"Agent tools must return a dict of outputs. Got {type(outputs)} instead.")
            state = TaskState.SUCCEEDED
        except Exception as e:
            if context.is_cancelled:
                # If cancelled, we log and return, without trying to set state, or outputs
                # or sending completion messages
                LOG.debug(f"{Colors.WARNING}🛑 [{task.id}][{task.type}] Task cancelled.{Colors.ENDC}")
                return

            LOG.debug(f"{Colors.FAIL}❌ [{task.id}][{task.type}] Agent Error: {e}{Colors.ENDC}")
            state = TaskState.FAILED
            outputs = {"exception": str(e)}

        msg = TaskCompletionMessage(id=task.id, state=state, outputs=outputs, agent_id=self.launcher_id)
        self.task_completion_publisher.publish(msg)

    def on_task_ack(self, message: TaskCompletionAckMessage) -> None:
        if message.accepted_agent_id != self.launcher_id:
            with self.thread_lock:
                context = self.active_contexts.get(message.id)

            if context:
                # It's a running task, and we are not the winner.
                LOG.debug(f"{Colors.WARNING}📉 [{message.id}] received ACK for {message.accepted_agent_id}, cancelling local execution.{Colors.ENDC}")
                context.cancel()

    def reload_agents(self):
        LOG.debug(f"{Colors.OKBLUE}Reloading agents...{Colors.ENDC}")

        # Dispose of existing agents before reloading
        for agent in self.agents.values():
            try:
                agent.dispose()
            except Exception as e:
                LOG.debug(f"Error disposing agent during reload: {e}")

        _get_plugin_manager().reload_plugins()
        self._initialize_agents()
