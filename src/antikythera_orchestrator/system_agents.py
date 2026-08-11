import time
from typing import Any
from typing import Dict
from typing import TypedDict

import compas
from compas.datastructures import Mesh

from antikythera.models import Task
from antikythera_agents.annotations import Param
from antikythera_agents.base_agent import Agent
from antikythera_agents.cli import Colors
from antikythera_agents.decorators import agent
from antikythera_agents.decorators import tool


class StartResult(TypedDict):
    process_start_time: float


class EndResult(TypedDict):
    process_end_time: float


class DemoMeshResult(TypedDict):
    mesh: Mesh


@agent(type="system")
class SystemAgent(Agent):
    @tool(name="composite")
    def composite(self, task: Task) -> Dict[str, Any]:
        """Trigger for a composite (virtual) task.

        Stays opaque (`task: Task`) permanently: a composite task has no fixed shape of
        its own, it returns whatever outputs the blueprint that declares it asks for, so
        there is no single `TypedDict` that could describe every composite task's output
        across every blueprint (ADR-0002, issue-td-11).
        """
        print(f"{Colors.OKBLUE}✅ [{task.id}][{task.type}] Composite trigger {Colors.ENDC}")

        # Composite tasks need to return a clean list of expected outputs.
        # Since they are virtual, they don't produce values, so we return keys with None values.
        return {o.name: None for o in task.outputs}

    @tool(name="start")
    def start_process(self) -> StartResult:
        """Mark the beginning of a blueprint run.

        Returns
        -------
        process_start_time
            Unix timestamp, in seconds, taken when the process started.
        """
        print(f"{Colors.OKBLUE}🏃 [system.start] Starting...{Colors.ENDC}")
        print(f"{Colors.OKGREEN}✅ [system.start] Finished.{Colors.ENDC}")
        return {"process_start_time": time.time()}

    @tool(name="end")
    def end_process(self) -> EndResult:
        """Mark the end of a blueprint run.

        Returns
        -------
        process_end_time
            Unix timestamp, in seconds, taken when the process ended.
        """
        print(f"{Colors.OKBLUE}🏃 [system.end] Starting...{Colors.ENDC}")
        print(f"{Colors.OKGREEN}✅ [system.end] Finished.{Colors.ENDC}")
        return {"process_end_time": time.time()}

    @tool(name="sleep")
    def sleep_process(self, task: Task, duration: Param[float] = 1) -> Dict[str, Any]:
        """Sleep for `duration` seconds, blocking the agent.

        Stays opaque (`task: Task`): `duration` is its only real argument, already
        exposed via `Param[float]`, and `Task` is kept solely to log the sleeping task's
        id and type (ADR-0002, issue-td-11).

        Parameters
        ----------
        duration
            How long to sleep, in seconds. Defaults to 1.
        """
        print(f"{Colors.OKBLUE}😴 [{task.id}][{task.type}] Sleeping for {duration}s...{Colors.ENDC}")
        time.sleep(duration)
        print(f"{Colors.OKGREEN}✅ [{task.id}][{task.type}] Finished sleeping.{Colors.ENDC}")
        return {}

    @tool(name="demo_mesh")
    def demo_mesh(self) -> DemoMeshResult:
        """Load the bundled COMPAS Stanford bunny demo mesh.

        Returns
        -------
        mesh
            The demo mesh.
        """
        return {"mesh": Mesh.from_ply(compas.get_bunny())}
