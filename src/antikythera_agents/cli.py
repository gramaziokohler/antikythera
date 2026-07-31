from __future__ import annotations

import argparse
import logging
import time

MQTT_LOG_TOPIC = "antikythera/logs"


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


def _run(args: argparse.Namespace) -> None:
    from mqtthandler import MQTTHandler

    from antikythera_agents.launcher import AgentLauncher
    from antikythera_agents.launcher import _get_plugin_manager

    print("Antikythera Agents starting up...")
    print(f"Connecting to MQTT broker at {args.broker_host}:{args.broker_port}")
    launcher = AgentLauncher(broker_host=args.broker_host, broker_port=args.broker_port, sys_only=args.sys_only)
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


def _describe(args: argparse.Namespace) -> None:
    import json
    import sys

    from antikythera.plugin import PLUGIN_MANAGER
    from antikythera_agents.decorators import get_agent_tools
    from antikythera_agents.decorators import get_tool_descriptor
    from antikythera_agents.decorators import list_registered_agents

    failures = PLUGIN_MANAGER.discover_plugins_strict()

    if failures and not args.allow_partial:
        for name, error in failures:
            print(f"Failed to load plugin {name}: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)

    catalog = []
    for agent_type, agent_class in sorted(list_registered_agents().items()):
        tools = [get_tool_descriptor(agent_class, tool_name).to_dict(agent_type) for tool_name in sorted(get_agent_tools(agent_class))]
        catalog.append({"agent": agent_type, "tools": tools})

    if failures:
        result = {
            "agents": catalog,
            "failed": [{"name": name, "error": f"{type(error).__name__}: {error}"} for name, error in failures],
        }
    else:
        result = catalog

    print(json.dumps(result, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="antikythera-agents", description="Antikythera Agents")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Start the agent launcher.")
    run_parser.add_argument("--broker-host", default="127.0.0.1", help="MQTT broker host.")
    run_parser.add_argument("--broker-port", type=int, default=1883, help="MQTT broker port.")
    run_parser.add_argument("--dev", action="store_true", help="Enable hot reloading of agents.")
    run_parser.add_argument("--sys-only", action="store_true", help="Only start system agents (agent type 'system').")
    run_parser.set_defaults(func=_run)

    describe_parser = subparsers.add_parser("describe", help="Emit the tool catalog as JSON.")
    describe_parser.add_argument("--format", choices=["json"], default="json", help="Output format (only 'json' is supported).")
    describe_parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Emit the catalog even if some plugins failed to import, recording the gaps in a 'failed' section.",
    )
    describe_parser.set_defaults(func=_describe)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
