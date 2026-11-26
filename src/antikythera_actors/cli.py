from __future__ import annotations

import argparse
import importlib
import importlib.util
import logging
import os
import sys

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


def _import_actor_module(spec: str):
    """Import a module that defines actors, given as a ``.py`` file path or a dotted module name."""
    if spec.endswith(".py") or os.path.sep in spec or "/" in spec:
        path = os.path.abspath(spec)
        if not os.path.isfile(path):
            raise SystemExit(f"Actor file not found: {spec}")
        # Like running the file as a script: its folder is importable, so sibling modules resolve.
        folder = os.path.dirname(path)
        if folder not in sys.path:
            sys.path.insert(0, folder)
        name = os.path.splitext(os.path.basename(path))[0]
        module_spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[name] = module
        module_spec.loader.exec_module(module)
        return module
    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())
    return importlib.import_module(spec)


def _load_actors(specs: list[str]) -> list[str]:
    """Import the given actor modules and return the actor types they registered."""
    loaded = set()
    for spec in specs:
        module = _import_actor_module(spec)
        for value in vars(module).values():
            if isinstance(value, type) and getattr(value, "__module__", None) == module.__name__ and hasattr(value, "_actor_type"):
                loaded.add(value._actor_type)
    loaded = sorted(loaded)
    if not loaded:
        raise SystemExit(f"No actors found in: {', '.join(specs)}. Actors are classes decorated with @actor(type=...).")
    return loaded


def _run(args: argparse.Namespace) -> None:
    from mqtthandler import MQTTHandler

    from antikythera_actors.launcher import ActorLauncher
    from antikythera_actors.launcher import _get_plugin_manager
    from antikythera_actors.serve import serve_forever

    if args.dev and args.actor:
        raise SystemExit("--dev reloads actors installed as plugins; it cannot be combined with --actor.")

    actor_types = args.only
    if args.actor:
        loaded = _load_actors(args.actor)
        actor_types = [t for t in loaded if t in args.only] if args.only else loaded

    print("Antikythera Actors starting up...", flush=True)
    print(f"Connecting to MQTT broker at {args.broker_host}:{args.broker_port}", flush=True)
    try:
        launcher = ActorLauncher(
            broker_host=args.broker_host,
            broker_port=args.broker_port,
            sys_only=args.sys_only,
            mqtt_transport=args.mqtt_transport,
            tls=args.tls,
            actor_types=actor_types,
            discover=not args.actor,
        )
    except ValueError as e:
        raise SystemExit(str(e))

    if args.dev:
        _get_plugin_manager().start_file_watcher(launcher.reload_actors)
        print(f"{Colors.OKGREEN}Hot reloading enabled.{Colors.ENDC}", flush=True)

        # Configure MQTT logging
        handler = MQTTHandler(args.broker_host, MQTT_LOG_TOPIC, port=args.broker_port)
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        handler.setFormatter(formatter)

        actor_logger = logging.getLogger("antikythera_actors")
        actor_logger.addHandler(handler)
        actor_logger.setLevel(logging.DEBUG)

        print(f"{Colors.OKGREEN}MQTT logging handler configured on {MQTT_LOG_TOPIC}.{Colors.ENDC}", flush=True)

    serve_forever(launcher, on_stop=_get_plugin_manager().stop_file_watcher if args.dev else None)


def _describe(args: argparse.Namespace) -> None:
    import json
    import sys

    from antikythera.plugin import PLUGIN_MANAGER
    from antikythera_actors.decorators import get_actor_tools
    from antikythera_actors.decorators import get_tool_descriptor
    from antikythera_actors.decorators import list_registered_actors

    failures = PLUGIN_MANAGER.discover_plugins_strict()

    if failures and not args.allow_partial:
        for name, error in failures:
            print(f"Failed to load plugin {name}: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)

    catalog = []
    for actor_type, actor_class in sorted(list_registered_actors().items()):
        tools = [get_tool_descriptor(actor_class, tool_name).to_dict(actor_type) for tool_name in sorted(get_actor_tools(actor_class))]
        catalog.append({"actor": actor_type, "tools": tools})

    if failures:
        result = {
            "actors": catalog,
            "failed": [{"name": name, "error": f"{type(error).__name__}: {error}"} for name, error in failures],
        }
    else:
        result = catalog

    print(json.dumps(result, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="antikythera-actors", description="Antikythera Actors")
    subparsers = parser.add_subparsers(dest="command", required=True)

    from antikythera import config

    run_parser = subparsers.add_parser(
        "run",
        help="Start the actor launcher.",
        description=(
            "Run actors and connect them to an orchestrator over MQTT. By default every actor installed as a plugin runs. "
            "With --actor, only the actors defined in the given files or modules run, so that, for example, "
            "`uvx --from antikythera-sdk antikythera-actors run --actor my_actor.py` puts a single actor on the network."
        ),
    )
    run_parser.add_argument("--broker-host", default=config.MQTT_BROKER_HOST, help="MQTT broker host (env: MQTT_BROKER_HOST).")
    run_parser.add_argument("--broker-port", type=int, default=config.MQTT_BROKER_PORT, help="MQTT broker port (env: MQTT_BROKER_PORT).")
    run_parser.add_argument("--mqtt-transport", choices=["tcp", "websockets"], default="tcp", help="MQTT socket transport.")
    run_parser.add_argument("--tls", action="store_true", help="Connect to the MQTT broker over TLS.")
    run_parser.add_argument(
        "--actor",
        action="append",
        metavar="FILE_OR_MODULE",
        help="Run the actors defined in this .py file or importable module, instead of the installed plugins. Repeatable.",
    )
    run_parser.add_argument("--only", action="append", metavar="ACTOR_TYPE", help="Only run actors of this type. Repeatable.")
    run_parser.add_argument("--dev", action="store_true", help="Enable hot reloading of actors.")
    run_parser.add_argument("--sys-only", action="store_true", help="Only start system actors (actor type 'system').")
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
