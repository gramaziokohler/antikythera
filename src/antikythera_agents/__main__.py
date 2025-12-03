from __future__ import annotations

import argparse
import logging
import time

from mqtthandler import MQTTHandler

from antikythera_agents.cli import Colors
from antikythera_agents.launcher import AgentLauncher
from antikythera_agents.launcher import _get_plugin_manager

MQTT_LOG_TOPIC = "antikythera/logs"


def main():
    parser = argparse.ArgumentParser(description="Antikythera Agents")
    parser.add_argument("--broker-host", default="127.0.0.1", help="MQTT broker host.")
    parser.add_argument("--broker-port", type=int, default=1883, help="MQTT broker port.")
    parser.add_argument("--dev", action="store_true", help="Enable hot reloading of agents.")
    args = parser.parse_args()

    print("Antikythera Agents starting up...")
    print(f"Connecting to MQTT broker at {args.broker_host}:{args.broker_port}")
    launcher = AgentLauncher(broker_host=args.broker_host, broker_port=args.broker_port)
    launcher.start()

    if args.dev:
        _get_plugin_manager().start_file_watcher(launcher.reload_agents)
        print(f"{Colors.OKGREEN}Hot reloading enabled.{Colors.ENDC}")

        # Configure MQTT logging
        handler = MQTTHandler(args.broker_host, MQTT_LOG_TOPIC, port=args.broker_port)
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        handler.setFormatter(formatter)

        agent_logger = logging.getLogger("antikythera_agents")
        agent_logger.addHandler(handler)
        agent_logger.setLevel(logging.DEBUG)

        print(f"{Colors.OKGREEN}MQTT logging handler configured on {MQTT_LOG_TOPIC}.{Colors.ENDC}")

    print("Agents are running and waiting for tasks. Press Ctrl+C to shut down.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down agents...")
        launcher.stop()
        if args.dev:
            _get_plugin_manager().stop_file_watcher()
        print("Agents stopped.")

    print("Bye!")


if __name__ == "__main__":
    main()
