from __future__ import annotations

from antikythera_agents.agent import Agent
from compas_eve import Message, Topic
from compas_eve.mqtt import MqttTransport


class SystemAgent(Agent):
    """An agent for handling system-level tasks."""

    def subscribe(self) -> None:
        """Subscribes the agent to system task topics."""
        start_topic = Topic("antikythera/task/system.start/start")
        end_topic = Topic("antikythera/task/system.end/start")
        self.transport.subscribe(start_topic, self.on_message)
        self.transport.subscribe(end_topic, self.on_message)
        print(f"SystemAgent subscribed to: {start_topic}")
        print(f"SystemAgent subscribed to: {end_topic}")

    def on_message(self, topic: Topic, message: Message) -> None:
        """Handles incoming task requests."""
        task_id = message.payload.get("id")
        task_type = message.payload.get("type")
        print(f"SystemAgent received task: {task_id} ({task_type})")

        # Simulate work
        print(f"Executing task {task_id}...")

        # Publish task done message
        done_topic = Topic(f"antikythera/task/{task_id}/done")
        done_message = Message(payload={"task_id": task_id, "status": "succeeded"})
        self.transport.publish(done_topic, done_message)
        print(f"SystemAgent published done message for task: {task_id}")
