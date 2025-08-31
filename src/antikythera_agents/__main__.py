from __future__ import annotations

import argparse
import sys
import threading
import time
from typing import Callable


class Colors:
    """ANSI color codes for terminal output."""
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKCYAN = "\033[96m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"

from compas_eve import Message
from compas_eve import Publisher
from compas_eve import Subscriber
from compas_eve import Topic
from compas_eve.mqtt import MqttTransport

from antikythera.models import Task


# @agent(type="system.start")
class Agent:
    """An agent for handling system-level tasks."""
    # pre_state: pending
    # post_state: ready | failed
    def __init__(self):
        pass

    # pre_state: running
    # post_state: succeeded | failed
    def run(self, task: Task) -> dict:
        pass
        # print("System start agent started.")
        # return {"result": "success"}
        
    # pre_state: succeeded | failed
    # post_state: succeeded | failed
    def dispose(self):
        pass

class AgentManager:
    def __init__(self, callback: Callable[[Task], dict]):
        self.callback = callback


def system_start(task: Task) -> dict:
    print(f"{Colors.OKBLUE}🏃 [{task.id}][{task.type}] Starting...{Colors.ENDC}")
    time.sleep(1)
    print(f"{Colors.OKGREEN}✅ [{task.id}][{task.type}] Finished.{Colors.ENDC}")
    return {"process_start_time": time.time()}


def system_end(task: Task) -> dict:
    print(f"{Colors.OKBLUE}🏃 [{task.id}][{task.type}] Starting...{Colors.ENDC}")
    time.sleep(1)
    print(f"{Colors.OKGREEN}✅ [{task.id}][{task.type}] Finished.{Colors.ENDC}")
    return {"process_end_time": time.time()}


def system_sleep(task: Task) -> dict:
    duration = task.params.get("duration", 1)
    print(f"{Colors.OKBLUE}😴 [{task.id}][{task.type}] Sleeping for {duration}s...{Colors.ENDC}")
    time.sleep(duration)
    print(f"{Colors.OKGREEN}✅ [{task.id}][{task.type}] Finished sleeping.{Colors.ENDC}")
    return None


def user_interaction_user_input(task: Task) -> dict:
    print(f"{Colors.HEADER}✍️ [{task.id}][{task.type}] Awaiting user input...{Colors.ENDC}")
    result = {}
    for key in task.outputs:
        result[key] = input(f"    [{task.id}][{task.type}] > Enter {key}: ")
    print(f"{Colors.OKGREEN}✅ [{task.id}][{task.type}] Input received.{Colors.ENDC}")
    return result


def user_interaction_user_output(task: Task) -> dict:
    print(f"{Colors.OKCYAN}💬 [{task.id}][{task.type}] Displaying output:{Colors.ENDC}")
    for key, value in task.inputs.items():
        print(f"    [{task.id}][{task.type}] > {key}: {value}")
    print(f"{Colors.OKGREEN}✅ [{task.id}][{task.type}] Finished displaying output.{Colors.ENDC}")
    return None


TASK_HANDLERS = {
    "system.start": system_start,
    "system.end": system_end,
    "system.sleep": system_sleep,
    "user_interaction.user_input": user_interaction_user_input,
    "user_interaction.user_output": user_interaction_user_output,
}


class AgentLauncher:
    def __init__(self, broker_host="127.0.0.1", broker_port=1883):
        self.threads = []
        self.thread_lock = threading.Lock()
        self.transport = MqttTransport(host=broker_host, port=broker_port)
        self.task_start_subscriber = Subscriber(Topic("antikythera/task/start"), self.on_task_start, transport=self.transport)
        self.task_completion_publisher = Publisher(Topic("antikythera/task/completed"), transport=self.transport)

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
        handler = TASK_HANDLERS.get(task.type)
        if not handler:
            print(f"{Colors.WARNING}⚠️  [WARNING] No handler for task type: {task.type}{Colors.ENDC}")
            return

        try:
            outputs = handler(task)
            state = "succeeded"
        except Exception as e:
            print(f"{Colors.FAIL}❌ [{task.id}][{task.type}] Error: {e}{Colors.ENDC}")
            state = "failed"
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
