from __future__ import annotations

import time
from typing import Callable

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
    print("System start")
    time.sleep(1)
    return {"process_start_time": time.time()}

def system_end(task: Task) -> dict:
    print("System end")
    time.sleep(1)
    return {"process_end_time": time.time()}

def system_sleep(task: Task) -> dict:
    print(f"System sleep {task.params['duration']} seconds")
    time.sleep(task.params["duration"])
    return None

def user_interaction_user_input(task: Task) -> dict:
    print("User input!")
    result = {}
    for key in task.outputs:
        result[key] = input(f"Enter {key}: ")
    return result

def user_interaction_user_output(task: Task) -> dict:
    print("User output!")
    for key in task.inputs:
        print(f"{key}: {task.inputs[key]}")
    return None

class AgentLauncher:
    def __init__(self, broker_host="127.0.0.1", broker_port=1883) -> None:
        self.transport = MqttTransport(host=broker_host, port=broker_port)
        self.task_completion_publisher = Publisher(Topic("antikythera/task/completed"), transport=self.transport)
        self.task_start_subscriber = Subscriber(Topic("antikythera/task/start"), self.on_task_start, transport=self.transport)
        self.task_start_subscriber.subscribe()

        # TODO: This service should launch agent managers for each type of available agents, so that they are ready to run
        # For now, this is hard-coded
        self.agent_managers = {
            "system.start": AgentManager(system_start),
            "system.end": AgentManager(system_end),
            "system.sleep": AgentManager(system_sleep),
            "user_interaction.user_input": AgentManager(user_interaction_user_input),
            "user_interaction.user_output": AgentManager(user_interaction_user_output),
        }


    def on_task_start(self, message: Message) -> None:
        print(f"Task start received: {message}")
        task = Task(
            id=message["id"],
            type=message["type"],
            inputs=message["inputs"],
            outputs=message["outputs"],
            params=message["params"],
        )
        try:
            state = "succeeded"
            # RUN THE TASK!
            outputs = self.agent_managers[task.type].callback(task)
        except Exception as e:
            state = "failed"
            outputs = {"exception": str(e)}
        msg = Message({"id": task.id, "state": state, "outputs": outputs})
        print(f"Task completed: {task.id} ({msg})")
        self.task_completion_publisher.publish(msg)


def main():
    """Main entry point for running Antikythera agents."""
    # parser = argparse.ArgumentParser(description="Antikythera: Agent launcher.")
    # parser.add_argument("agent_type", help="The type of agent to run (e.g., 'system').")
    # args = parser.parse_args()

    broker_host, broker_port = "127.0.0.1", 1883
    launcher = AgentLauncher(broker_host, broker_port)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down...")
        launcher.task_start_subscriber.unsubscribe()

    print("Bye!")


if __name__ == "__main__":
    main()
