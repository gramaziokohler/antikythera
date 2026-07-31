"""Reference agent: the worked example for the tool convention (ADR-0002, ADR-0003).

Copy from this file when authoring a new agent. Its three tools between them exercise
every annotation kind the binder understands — a plain task input, an explicit `Input[T]`,
a required and a defaulted `Param[T]`, a `Context[T]` value, an `Optional[T]` input, a
`TypedDict` return with both a required and a `NotRequired` key, the `Task` escape hatch,
and `ExecutionContext` cancellation. It has no dependency beyond this package, so it runs
anywhere the launcher does, including CI. See `examples/reference_agent_demo.json` for a
blueprint that drives it end to end, and ARCHITECTURE.md's "Reference Agent" section.
"""

import time
from typing import Any
from typing import Dict
from typing import NotRequired
from typing import Optional
from typing import TypedDict

from antikythera.models import Task
from antikythera_agents.annotations import Context
from antikythera_agents.annotations import Input
from antikythera_agents.annotations import Param
from antikythera_agents.base_agent import Agent
from antikythera_agents.context import ExecutionContext
from antikythera_agents.decorators import agent
from antikythera_agents.decorators import tool

AssembleResult = TypedDict("AssembleResult", {"message": str, "detail": NotRequired[str]})


@agent(type="reference")
class ReferenceAgent(Agent):
    """Worked example agent exercising every part of the tool convention.

    Not a real fabrication tool: it exists so an agent author has a small, dependency-free
    file to copy from, and so the binder is exercised by combinations no first-party tool
    puts it through (ADR-0002, issue-td-10).
    """

    @tool(name="assemble")
    def assemble(
        self,
        title: str,
        subtitle: Input[str],
        tag: Param[str],
        element_id: Context[str] = "unassigned",
        repeat: Param[int] = 1,
        note: Optional[str] = None,
    ) -> AssembleResult:
        """Combine a title, subtitle and tag into a message, repeated `repeat` times.

        Parameters
        ----------
        title : str
            A plain task input, bound by name exactly like `subtitle`.
        subtitle : str
            A task input declared explicitly with `Input[str]` — binds identically to
            `title`, an unannotated parameter.
        tag : str
            A required task parameter (`Param[str]`, no default).
        element_id : str, optional
            The expansion-context key this tool wants (`Context[str]`); falls back to its
            default outside a dynamic expansion, and binds per element inside one.
        repeat : int, optional
            A task parameter with a default (`Param[int] = 1`).
        note : str, optional
            An optional task input that legitimately accepts nothing.

        Returns
        -------
        message : str
            The assembled, repeated message.
        detail : str, optional
            Present only when `note` was given.
        """
        message = " ".join([f"{title} — {subtitle} [{tag}/{element_id}]"] * repeat)
        result: AssembleResult = {"message": message}
        if note is not None:
            result["detail"] = note
        return result

    @tool(name="wait")
    def wait(self, seconds: Param[float], context: ExecutionContext) -> Dict[str, Any]:
        """Sleep in small increments, stopping early if the run is cancelled.

        Parameters
        ----------
        seconds : float
            Total time to sleep, in seconds, absent cancellation.

        Returns
        -------
        dict
            `cancelled`: whether the wait was interrupted by cancellation.
        """
        step = 0.01
        elapsed = 0.0
        while elapsed < seconds:
            if context is not None and context.is_cancelled:
                return {"cancelled": True}
            time.sleep(step)
            elapsed += step
        return {"cancelled": False}

    @tool(name="passthrough")
    def passthrough(self, task: Task) -> Dict[str, Any]:
        """The `Task` escape hatch: reads `task.inputs` directly, opaque to strict binding.

        Returns
        -------
        dict
            Every declared input's name mapped to its resolved value.
        """
        return {i.name: i.value for i in task.inputs}
