import logging
from abc import ABC
from contextlib import contextmanager
from typing import Any
from typing import Dict

from antikythera.models import Task
from antikythera_agents.decorators import get_agent_tools


class Agent(ABC):
    """Base class for all Antikythera agents.

    An agent is responsible for executing tasks of a specific type.
    Each agent can have multiple tools (methods) that handle different operations.
    """

    def __init__(self):
        """Initialize the agent and allocate any required resources.

        Notes
        -----
        Override this method to set up connections, load models, etc.
        """
        self._tools = get_agent_tools(self.__class__)
        self._initialized = True
        self.logger = logging.getLogger(f"{self.__class__.__module__}.{self.__class__.__name__}")

    def dispose(self):
        """Clean up resources and perform shutdown operations.

        Notes
        -----
        Override this method to close connections, save state, etc.
        """
        self._initialized = False

    @contextmanager
    def managed_execution(self):
        """Context manager for safe agent execution with proper resource management."""
        try:
            if not hasattr(self, "_initialized") or not self._initialized:
                raise RuntimeError("Agent not properly initialized")
            yield self
        except Exception as e:
            # Log or handle execution errors
            raise e
        finally:
            # Could add cleanup logic here if needed
            pass

    def execute_task(self, task: Task) -> Dict[str, Any]:
        """Execute a task using the appropriate tool.

        Parameters
        ----------
        task : Task
            The task to execute

        Returns
        -------
        dict
            Dictionary of outputs from the tool execution

        Raises
        ------
        ValueError
            If no tool is found for the task type
        RuntimeError
            If task execution fails
        """
        with self.managed_execution():
            # Determine which tool to use
            # For now, we'll use a simple mapping: task.type -> tool_name
            # Later this could be more sophisticated
            tool_name = self._get_tool_for_task(task)

            if tool_name not in self._tools:
                available_tools = list(self._tools.keys())
                raise ValueError(f"No tool '{tool_name}' found for task type '{task.type}'. Available tools: {available_tools}")

            tool_method = self._tools[tool_name]

            # Execute the tool
            try:
                result = tool_method(self, task)
                return result or {}
            except Exception as e:
                self.logger.exception(f"Tool '{tool_name}' execution failed")
                raise RuntimeError(f"Tool '{tool_name}' execution failed: {str(e)}") from e

    def _get_tool_for_task(self, task: Task) -> str:
        """Determine which tool should handle a given task.

        Default implementation extracts the tool name from the task type.
        For example: "system.start" -> "start", "user_interaction.input" -> "input"

        Parameters
        ----------
        task : Task
            The task to analyze

        Returns
        -------
        str
            The tool name to use

        Notes
        -----
        Override this method for custom tool selection logic.
        """
        if "." in task.type:
            return task.type.split(".", 1)[1]
        return task.type

    def list_tools(self) -> Dict[str, str]:
        """List all available tools for this agent.

        Returns
        -------
        dict
            Dictionary mapping tool names to their method names
        """
        return {name: method.__name__ for name, method in self._tools.items()}

    def has_tool(self, tool_name: str) -> bool:
        """Check if this agent has a specific tool.

        Parameters
        ----------
        tool_name : str
            Name of the tool to check for

        Returns
        -------
        bool
            True if the tool exists, False otherwise
        """
        return tool_name in self._tools

    def __enter__(self):
        """Support for context manager usage."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Clean up when used as context manager."""
        self.dispose()

    def __repr__(self):
        agent_type = getattr(self.__class__, "_agent_type", "unknown")
        tool_count = len(self._tools)
        return f"<{self.__class__.__name__}(type='{agent_type}', tools={tool_count})>"
