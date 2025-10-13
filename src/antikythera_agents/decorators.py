from functools import wraps
from typing import Callable
from typing import Dict
from typing import Optional

# Agent & Tool registries
_AGENT_REGISTRY: Dict[str, type] = {}
_TOOL_REGISTRY: Dict[type, Dict[str, Callable]] = {}


def agent(type: str):
    """Decorator to register an agent class with a specific type.

    Parameters
    ----------
    type : str
        The agent type identifier (e.g., "system", "user_interaction")

    Examples
    --------
    >>> @agent(type="system")
    ... class SystemAgent(Agent):
    ...     pass
    """

    def decorator(cls):
        if not hasattr(cls, "_agent_type"):
            cls._agent_type = type

        # Register the agent class
        _AGENT_REGISTRY[type] = cls

        # Initialize tool registry for this class if not exists
        if cls not in _TOOL_REGISTRY:
            _TOOL_REGISTRY[cls] = {}

        return cls

    return decorator


def tool(name: Optional[str] = None):
    """Decorator to mark a method as a tool within an agent.

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

        return wrapper

    return decorator


def get_agent_class(agent_type: str) -> Optional[type]:
    """Get the agent class for a given type.

    Parameters
    ----------
    agent_type : str
        The agent type identifier

    Returns
    -------
    type or None
        The agent class if found, None otherwise
    """
    return _AGENT_REGISTRY.get(agent_type)


def get_agent_tools(agent_class: type) -> Dict[str, Callable]:
    """Get all tools for a given agent class.

    Parameters
    ----------
    agent_class : type
        The agent class to scan for tools

    Returns
    -------
    dict
        Dictionary mapping tool names to their methods
    """
    tools = {}

    # Scan the class for tool methods
    for attr_name in dir(agent_class):
        if attr_name.startswith("__"):
            continue

        attr = getattr(agent_class, attr_name)
        if hasattr(attr, "_is_tool") and attr._is_tool:
            tool_name = getattr(attr, "_tool_name", attr_name)
            tools[tool_name] = attr

    return tools


def list_registered_agents() -> Dict[str, type]:
    """List all registered agent types and their classes.

    Returns
    -------
    dict
        Dictionary mapping agent type strings to their classes
    """
    return _AGENT_REGISTRY.copy()
