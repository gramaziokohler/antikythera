import glob
import os
import shutil
from typing import Any
from typing import Dict

from antikythera_agents.base_agent import Agent
from antikythera_agents.decorators import agent
from antikythera_agents.decorators import tool


@agent(type="io")
class IOAgent(Agent):
    """Agent for Input/Output operations."""

    @tool(name="copy")
    def copy_file(self, source: str, destination: str) -> Dict[str, Any]:
        """Copy files matching source glob pattern to destination.

        Parameters
        ----------
        source : str
            Glob pattern for the files to copy.
        destination : str
            Destination path to copy the matched files to.

        Returns
        -------
        dict
            Dictionary containing 'copied_files' and 'destination'.
        """
        sources = glob.glob(source, recursive=True)

        if not sources:
            self.logger.warning(f"No files found matching pattern: {source}")
            return {"copied_files": [], "destination": destination}

        # If matching multiple files, destination must be a directory
        if len(sources) > 1:
            if os.path.exists(destination) and not os.path.isdir(destination):
                raise ValueError(f"Destination '{destination}' is a file, but source matched multiple files. Destination must be a directory.")
            if not os.path.exists(destination):
                os.makedirs(destination)

        copied_files = []
        try:
            for matched_source in sources:
                if os.path.isfile(matched_source):
                    self.logger.info(f"Copying file from {matched_source} to {destination}")
                    shutil.copy2(matched_source, destination)
                    copied_files.append(matched_source)
                elif os.path.isdir(matched_source):
                    self.logger.info(f"Skipping directory {matched_source}")
        except Exception as e:
            raise RuntimeError(f"Failed to copy files: {e}") from e

        return {"copied_files": copied_files, "destination": destination}
