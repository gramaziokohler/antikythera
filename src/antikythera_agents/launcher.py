from __future__ import annotations

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
from antikythera.models import TaskOutput
from antikythera.models import TaskState
from antikythera.models.conversions import dict_to_inputs
from antikythera.models.conversions import dict_to_params
from antikythera.models.conversions import keys_to_outputs
from antikythera.models.conversions import outputs_to_dict
from antikythera_agents.cli import Colors

THREAD_JOIN_TIMEOUT = 10


def _get_eve_transport(host, port, codec):
    return MqttTransport(host=host, port=port, codec=codec)


def _ensure_agents():
    _get_plugin_manager().discover_plugins()


def _get_plugin_manager():
    from antikythera.plugin import PLUGIN_MANAGER

    return PLUGIN_MANAGER


class AgentLauncher:
    def __init__(self, broker_host="127.0.0.1", broker_port=1883):
        self.launcher_id = coolname.generate_slug(4)
        self.pending_claims = {}  # task_id -> Task

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
        print(f"Agent Launcher initialized with ID: {Colors.HEADER}{self.launcher_id}{Colors.ENDC}")

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
            print(f"Waiting for {thread_count} running tasks to complete...")

        deadline = time.time() + THREAD_JOIN_TIMEOUT

        for thread in active_threads:
            remaining_time = max(0, deadline - time.time())
            if remaining_time == 0 and thread.is_alive():
                print(f"Timeout reached, skipping join for {thread.name}")
                continue

            try:
                thread.join(remaining_time)
            except Exception as e:
                print(f"Error joining thread: {e}, continuing shutdown.")

        # Dispose of all agents
        for agent in self.agents.values():
            try:
                agent.dispose()
            except Exception as e:
                print(f"Error disposing agent: {e}")

    def _initialize_agents(self):
        from antikythera_agents.decorators import list_registered_agents

        _ensure_agents()

        registered_agents = list_registered_agents()
        for agent_type, agent_class in registered_agents.items():
            self.agents[agent_type] = agent_class()
            print(f"Initialized {agent_class.__name__} for type '{agent_type}' with {len(self.agents[agent_type].list_tools())} tools.")

        print(f"Total agents initialized: {len(self.agents)}")

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
                print(f"Received allocation for unknown or already processed task {task_id}")

    def _execute_task_wrapper(self, task: Task, agent_type: str) -> None:
        try:
            self._execute_task(task, agent_type)
        finally:
            with self.thread_lock:
                self.threads.remove(threading.current_thread())

    def _execute_task(self, task: Task, agent_type: str) -> None:
        agent = self.agents.get(agent_type)

        if not agent:
            print(f"{Colors.WARNING}⚠️  [WARNING] No agent found for task type: {task.type}{Colors.ENDC}")
            return

        try:
            outputs = agent.execute_task(task)
            if not isinstance(outputs, dict):
                raise ValueError(f"Agent tools must return a dict of outputs. Got {type(outputs)} instead.")
            state = TaskState.SUCCEEDED
        except Exception as e:
            print(f"{Colors.FAIL}❌ [{task.id}][{task.type}] Agent Error: {e}{Colors.ENDC}")
            state = TaskState.FAILED
            outputs = {"exception": str(e)}

        msg = TaskCompletionMessage(id=task.id, state=state, outputs=outputs, agent_id=self.launcher_id)
        self.task_completion_publisher.publish(msg)

    def on_task_ack(self, message: TaskCompletionAckMessage) -> None:
        pass

    def reload_agents(self):
        print(f"{Colors.OKBLUE}Reloading agents...{Colors.ENDC}")

        # Dispose of existing agents before reloading
        for agent in self.agents.values():
            try:
                agent.dispose()
            except Exception as e:
                print(f"Error disposing agent during reload: {e}")

        _get_plugin_manager().reload_plugins()
        self._initialize_agents()
