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
