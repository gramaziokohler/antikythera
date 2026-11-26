from functools import wraps
from typing import Callable
from typing import Dict
from typing import Optional

from antikythera_actors.descriptor import ToolDescriptor

# Actor & Tool registries
_ACTOR_REGISTRY: Dict[str, type] = {}
_TOOL_REGISTRY: Dict[type, Dict[str, ToolDescriptor]] = {}


def actor(type: str):
    """Decorator to register an actor class with a specific type.

    Parameters
    ----------
    type : str
        The actor type identifier (e.g., "system", "user_interaction")

    Examples
    --------
    >>> @actor(type="system")
    ... class SystemActor(Actor):
    ...     pass
    """

    def decorator(cls):
        if not hasattr(cls, "_actor_type"):
            cls._actor_type = type

        # Register the actor class
        _ACTOR_REGISTRY[type] = cls

        # Snapshot each tool's descriptor now, while the class attributes are still the
        # genuine decorated methods. This is what `get_tool_descriptor` reads at execution
        # time, so it stays correct even if a caller (e.g. a test) later monkeypatches the
        # tool method on the class itself.
        _TOOL_REGISTRY[cls] = {tool_name: method._descriptor for tool_name, method in get_actor_tools(cls).items()}

        return cls

    return decorator


def tool(name: Optional[str] = None):
    """Decorator to mark a method as a tool within an actor.

    Parameters
    ----------
    name : str, optional
        Optional tool name. If not provided, uses the method name.

    Examples
    --------
    >>> @tool(name="start_process")
    ... def start(self, task: Task) -> dict:
    ...     return {"result": "started"}
    """

    def decorator(func: Callable):
        tool_name = name or func.__name__

        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        # Mark the function as a tool
        wrapper._is_tool = True
        wrapper._tool_name = tool_name
        wrapper._descriptor = ToolDescriptor(func=func, name=tool_name)

        return wrapper

    return decorator


def get_actor_class(actor_type: str) -> Optional[type]:
    """Get the actor class for a given type.

    Parameters
    ----------
    actor_type : str
        The actor type identifier

    Returns
    -------
    type or None
        The actor class if found, None otherwise
    """
    return _ACTOR_REGISTRY.get(actor_type)


def get_actor_tools(actor_class: type) -> Dict[str, Callable]:
    """Get all tools for a given actor class.

    Parameters
    ----------
    actor_class : type
        The actor class to scan for tools

    Returns
    -------
    dict
        Dictionary mapping tool names to their methods
    """
    tools = {}

    # Scan the class for tool methods
    for attr_name in dir(actor_class):
        if attr_name.startswith("__"):
            continue

        attr = getattr(actor_class, attr_name)
        if hasattr(attr, "_is_tool") and attr._is_tool:
            tool_name = getattr(attr, "_tool_name", attr_name)
            tools[tool_name] = attr

    return tools


def list_registered_actors() -> Dict[str, type]:
    """List all registered actor types and their classes.

    Returns
    -------
    dict
        Dictionary mapping actor type strings to their classes
    """
    return _ACTOR_REGISTRY.copy()


def get_tool_descriptor(actor_class: type, tool_name: str) -> Optional[ToolDescriptor]:
    """Get the `ToolDescriptor` for a tool, as captured when its actor class was decorated.

    Parameters
    ----------
    actor_class : type
        The actor class the tool belongs to
    tool_name : str
        Name of the tool

    Returns
    -------
    ToolDescriptor or None
        The descriptor if found, None otherwise
    """
    return _TOOL_REGISTRY.get(actor_class, {}).get(tool_name)
