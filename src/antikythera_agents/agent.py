from __future__ import annotations

import time

from compas_eve import Message
from compas_eve import Topic
from compas_eve.mqtt import MqttTransport


class Agent:
    """A base class for agents that execute tasks.

    Parameters
    ----------
    broker_host : str, optional
        The hostname of the MQTT broker, by default "127.0.0.1".
    broker_port : int, optional
        The port of the MQTT broker, by default 1883.

    """

    def __init__(self, broker_host="127.0.0.1", broker_port=1883):
        self.transport = MqttTransport(host=broker_host, port=broker_port)

    def on_message(self, topic: Topic, message: Message) -> None:
        """Handles incoming MQTT messages."""
        raise NotImplementedError

    def start(self) -> None:
        """Starts the agent's event loop."""
        self.transport.on_ready(self.subscribe)
        try:
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            print(f"\n{self.__class__.__name__} shutting down.")
        finally:
            self.transport.close()

    def subscribe(self) -> None:
        """Subscribes the agent to relevant topics."""
        pass  # To be implemented by subclasses
