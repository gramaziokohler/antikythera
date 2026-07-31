from __future__ import annotations

from typing import Annotated
from typing import TypeVar

T = TypeVar("T")


class _ParamMarker:
    """Marks a tool parameter as bound from `task.params`, by name."""

    def __repr__(self) -> str:
        return "Param"


Param = Annotated[T, _ParamMarker()]
"""Marks a tool parameter as a task parameter, bound by name from `task.params`.

Examples
--------
>>> @tool()
... def sleep_process(self, duration: Param[int] = 1) -> dict:
...     time.sleep(duration)
...     return {}
"""


class _InputMarker:
    """Marks a tool parameter as bound from `task.inputs`, by name."""

    def __repr__(self) -> str:
        return "Input"


Input = Annotated[T, _InputMarker()]
"""Marks a tool parameter as a task input, bound by name from `task.inputs`.

An unannotated parameter is already treated as a task input (ADR-0002); `Input[T]` exists
for authors who want to say so explicitly rather than by omission.

Examples
--------
>>> @tool()
... def copy_file(self, source: Input[str], destination: Input[str]) -> dict:
...     shutil.copy(source, destination)
...     return {}
"""


class _ContextMarker:
    """Marks a tool parameter as bound from the task's expansion context, by name."""

    def __repr__(self) -> str:
        return "Context"


Context = Annotated[T, _ContextMarker()]
"""Marks a tool parameter as bound from the task's expansion context, by name.

The expansion context is the identity of the item a dynamically expanded inner blueprint is
working on — `element_id`, and whatever else the `Sequencer` attaches. It lives on
`task.context` and is distinct from `ExecutionContext`, the cancellation/lifecycle handle.

Examples
--------
>>> @tool()
... def process_element(self, element_id: Context[str]) -> dict:
...     return {"element_id": element_id}
"""
