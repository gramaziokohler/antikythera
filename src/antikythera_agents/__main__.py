from __future__ import annotations

import argparse
import threading
import time

from compas_eve import Message
from compas_eve import Publisher
from compas_eve import Subscriber
from compas_eve import Topic
from compas_eve.mqtt import MqttTransport

from antikythera.models import Task
from antikythera.models import TaskState
from antikythera_agents.cli import Colors


def _ensure_agents():
    from antikythera.plugin import PLUGIN_MANAGER

    PLUGIN_MANAGER.discover_plugins()


class AgentLauncher:
    def __init__(self, broker_host="127.0.0.1", broker_port=1883):
        self.threads = []
        self.thread_lock = threading.Lock()
        self.transport = MqttTransport(host=broker_host, port=broker_port)
        self.task_start_subscriber = Subscriber(Topic("antikythera/task/start"), self.on_task_start, transport=self.transport)
        self.task_completion_publisher = Publisher(Topic("antikythera/task/completed"), transport=self.transport)

        self.agents = {}
        self._initialize_agents()

    def start(self):
        self.task_start_subscriber.subscribe()

    def stop(self):
        self.task_start_subscriber.unsubscribe()

        with self.thread_lock:
            active_threads = list(self.threads)
            thread_count = len(active_threads)

        if thread_count > 0:
            print(f"Waiting for {thread_count} running tasks to complete...")

        for thread in active_threads:
            thread.join()

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

    def on_task_start(self, message: Message) -> None:
        task = Task(
            id=message["id"],
            type=message["type"],
            inputs=message["inputs"],
            outputs=message["outputs"],
            params=message["params"],
        )

        thread = threading.Thread(target=self._execute_task_wrapper, args=(task,))
        with self.thread_lock:
            self.threads.append(thread)
        thread.start()

    def _execute_task_wrapper(self, task: Task) -> None:
        try:
            self._execute_task(task)
        finally:
            with self.thread_lock:
                self.threads.remove(threading.current_thread())

    def _execute_task(self, task: Task) -> None:
        agent_type = task.type.split(".")[0] if "." in task.type else task.type
        agent = self.agents.get(agent_type)

        if not agent:
            print(f"{Colors.WARNING}⚠️  [WARNING] No agent found for task type: {task.type}{Colors.ENDC}")
            return

        try:
            outputs = agent.execute_task(task)
            state = TaskState.SUCCEEDED.value
        except Exception as e:
            print(f"{Colors.FAIL}❌ [{task.id}][{task.type}] Agent Error: {e}{Colors.ENDC}")
            state = TaskState.FAILED.value
            outputs = {"exception": str(e)}

        msg = Message({"id": task.id, "state": state, "outputs": outputs})
        self.task_completion_publisher.publish(msg)


def main():
    parser = argparse.ArgumentParser(description="Antikythera Agents")
    parser.add_argument("--broker-host", default="127.0.0.1", help="MQTT broker host.")
    parser.add_argument("--broker-port", type=int, default=1883, help="MQTT broker port.")
    args = parser.parse_args()

    print("Antikythera Agents starting up...")
    print(f"Connecting to MQTT broker at {args.broker_host}:{args.broker_port}")
    launcher = AgentLauncher(broker_host=args.broker_host, broker_port=args.broker_port)
    launcher.start()
    print("Agents are running and waiting for tasks. Press Ctrl+C to shut down.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down agents...")
        launcher.stop()
        print("Agents stopped.")


if __name__ == "__main__":
    main()

    print("Bye!")
