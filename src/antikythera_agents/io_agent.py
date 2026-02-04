import glob
import os
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
        """Copy files matching source glob pattern to destination.

        Parameters
        ----------
        task : Task
            The task containing source (glob pattern) and destination paths.
            Paths can be provided via inputs or params.
            Required keys: 'source', 'destination'.

        Returns
        -------
        dict
            Dictionary containing 'copied_files' and 'destination'.
        """
        source_pattern = task.get_input_value("source") or task.get_param_value("source")
        destination = task.get_input_value("destination") or task.get_param_value("destination")

        if not source_pattern:
            raise ValueError("Source path or glob pattern is required (input or param 'source')")
        if not destination:
            raise ValueError("Destination path is required (input or param 'destination')")

        sources = glob.glob(source_pattern, recursive=True)

        if not sources:
            self.logger.warning(f"No files found matching pattern: {source_pattern}")
            return {"copied_files": [], "destination": destination}

        # If matching multiple files, destination must be a directory
        if len(sources) > 1:
            if os.path.exists(destination) and not os.path.isdir(destination):
                raise ValueError(f"Destination '{destination}' is a file, but source matched multiple files. Destination must be a directory.")
            if not os.path.exists(destination):
                os.makedirs(destination)

        copied_files = []
        try:
            for source in sources:
                if os.path.isfile(source):
                    self.logger.info(f"Copying file from {source} to {destination}")
                    shutil.copy2(source, destination)
                    copied_files.append(source)
                elif os.path.isdir(source):
                    self.logger.info(f"Skipping directory {source}")
        except Exception as e:
            raise RuntimeError(f"Failed to copy files: {e}")

        return {"copied_files": copied_files, "destination": destination}
