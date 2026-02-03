import subprocess
import sys

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        print("Running custom build hook: invoke generate-proto-classes")
        # Explicitly forward stdout/stderr to ensure output is visible
        subprocess.check_call(
            [sys.executable, "-m", "invoke", "generate-proto-classes"],
            cwd=self.root,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
