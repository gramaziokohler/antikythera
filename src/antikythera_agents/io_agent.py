import shutil
from typing import Any
from typing import Dict

from antikythera.models import Task
from antikythera_agents.base_agent import Agent
from antikythera_agents.decorators import agent
from antikythera_agents.decorators import tool


@agent(type="io")
class IOAgent(Agent):
    """Agent for Input/Output operations."""

    @tool(name="copy")
    def copy_file(self, task: Task) -> Dict[str, Any]:
        """Copy a file from source to destination.

        Parameters
        ----------
        task : Task
            The task containing source and destination paths.
            Paths can be provided via inputs or params.
            Required keys: 'source', 'destination'.

        Returns
        -------
        dict
            Dictionary containing 'source' and 'destination'.
        """
        source = task.get_input_value("source") or task.get_param_value("source")
        destination = task.get_input_value("destination") or task.get_param_value("destination")

        if not source:
            raise ValueError("Source path is required (input or param 'source')")
        if not destination:
            raise ValueError("Destination path is required (input or param 'destination')")

        self.logger.info(f"Copying file from {source} to {destination}")

        try:
            shutil.copy2(source, destination)
        except Exception as e:
            raise RuntimeError(f"Failed to copy file: {e}")

        return {"source": source, "destination": destination}
