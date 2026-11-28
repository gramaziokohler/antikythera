__author__ = ["Gonzalo Casas", "Chen Kasirer"]
__copyright__ = "Gramazio Kohler Research"
__license__ = "MIT License"
__email__ = ""
__version__ = "0.5.1"

# The public API, importable from the top level: `from antikythera import Blueprint, tool`,
# or `import antikythera as akt`. Names load on first use, so a program that only runs
# actors does not import the orchestrator and its dependencies.
_EXPORTS = {
    # Blueprints
    "Blueprint": "antikythera.models",
    "BlueprintSession": "antikythera.models",
    "Task": "antikythera.models",
    "TaskInput": "antikythera.models",
    "TaskOutput": "antikythera.models",
    "TaskParam": "antikythera.models",
    "Dependency": "antikythera.models",
    "OutputRef": "antikythera.models",
    "DependencyType": "antikythera.models",
    # Actors
    "Actor": "antikythera_actors",
    "ActorLauncher": "antikythera_actors",
    "actor": "antikythera_actors",
    "tool": "antikythera_actors",
    "run": "antikythera_actors",
    "Input": "antikythera_actors.annotations",
    "Param": "antikythera_actors.annotations",
    "Context": "antikythera_actors.annotations",
    "ExecutionContext": "antikythera_actors.context",
    # Orchestrator
    "Orchestrator": "antikythera_orchestrator",
    "InMemoryStorage": "antikythera_orchestrator",
    "InMemoryTransport": "antikythera.transports.memory",
    "MqttTransport": "antikythera.transports.mqtt",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module 'antikythera' has no attribute {name!r}")
    import importlib

    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(list(globals()) + __all__)
