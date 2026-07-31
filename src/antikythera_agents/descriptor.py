from __future__ import annotations

import inspect
import typing
from dataclasses import dataclass
from functools import cached_property
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional

from antikythera.models import Task
from antikythera_agents.annotations import _ParamMarker
from antikythera_agents.context import ExecutionContext


class ToolBindingError(Exception):
    """A task's inputs/params don't satisfy a tool's declared signature.

    Raised by `ToolDescriptor.bind` before the tool body runs, and reported under
    `TaskError.code == "TOOL_BINDING_ERROR"` rather than the `TOOL_FAILURE` used for
    exceptions raised by the tool itself — the mismatch is the blueprint's fault, not the
    tool's. See ADR-0002 and issue-td-04.
    """


def _unwrap(hint: Any) -> Any:
    """Strip an `Annotated[...]` wrapper down to the underlying type."""
    if getattr(hint, "__metadata__", None) is not None:
        return hint.__origin__
    return hint


def _is_param(hint: Any) -> bool:
    metadata = getattr(hint, "__metadata__", None)
    return bool(metadata) and any(isinstance(m, _ParamMarker) for m in metadata)


def _is_optional_type(tp: Any) -> bool:
    return typing.get_origin(tp) is typing.Union and type(None) in typing.get_args(tp)


def _type_hint_name(tp: Any) -> str:
    if tp is type(None):
        return "None"
    if isinstance(tp, type):
        return tp.__name__ if tp.__module__ == "builtins" else f"{tp.__module__}.{tp.__qualname__}"
    return str(tp).replace("typing.", "")


@dataclass(frozen=True)
class ToolField:
    """A single named, typed, optionally-optional field — shape shared by inputs and params."""

    name: str
    type_hint: str
    optional: bool

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "type_hint": self.type_hint, "optional": self.optional}


class ToolDescriptor:
    """Descriptor for a single tool, built by introspecting its signature.

    The same signature that binds arguments at execution time (`bind`) also produces the
    published catalog entry (`to_dict`), per ADR-0002. Type hints resolve lazily on first
    access, and are cached, so a module using `from __future__ import annotations` or
    containing a forward reference does not fail at import time.
    """

    def __init__(self, func: Callable, name: str):
        self.func = func
        self.name = name

    @cached_property
    def _signature(self) -> inspect.Signature:
        return inspect.signature(self.func)

    @cached_property
    def _hints(self) -> Dict[str, Any]:
        return typing.get_type_hints(self.func, include_extras=True)

    @cached_property
    def opaque(self) -> bool:
        """True for a tool that takes `Task` directly — no derivable inputs or outputs."""
        return any(_unwrap(hint) is Task for name, hint in self._hints.items() if name != "return")

    @cached_property
    def description(self) -> Optional[str]:
        doc = inspect.getdoc(self.func)
        if not doc:
            return None
        summary = doc.strip().split("\n\n")[0]
        return " ".join(summary.split())

    @cached_property
    def params(self) -> List[ToolField]:
        fields = []
        for name, hint in self._hints.items():
            if name == "return" or not _is_param(hint):
                continue
            inner = _unwrap(hint)
            sig_param = self._signature.parameters[name]
            has_default = sig_param.default is not inspect.Parameter.empty
            fields.append(ToolField(name=name, type_hint=_type_hint_name(inner), optional=has_default or _is_optional_type(inner)))
        return fields

    @cached_property
    def inputs(self) -> List[ToolField]:
        """Task inputs: every parameter that isn't `Task`, `ExecutionContext` or `Param[T]`.

        Covers both an unannotated parameter and one explicitly marked `Input[T]` — the two
        bind identically, per ADR-0002.
        """
        fields = []
        for name, hint in self._hints.items():
            if name == "return":
                continue
            unwrapped = _unwrap(hint)
            if unwrapped is Task or unwrapped is ExecutionContext or _is_param(hint):
                continue
            sig_param = self._signature.parameters[name]
            has_default = sig_param.default is not inspect.Parameter.empty
            fields.append(ToolField(name=name, type_hint=_type_hint_name(unwrapped), optional=has_default or _is_optional_type(unwrapped)))
        return fields

    @cached_property
    def outputs(self) -> List[Any]:
        # Output derivation from a TypedDict return type is issue-td-06.
        return []

    def bind(self, task: Task, context: Optional[ExecutionContext]) -> Dict[str, Any]:
        """Build the keyword arguments for invoking the tool from a task and context.

        Binding is strict for task inputs (ADR-0002, issue-td-04): an input the task declares
        that the tool doesn't accept, a required input the task doesn't supply, or a
        non-optional input resolving to `None` all raise `ToolBindingError` before the tool
        body runs — a wiring mismatch is the blueprint's fault, not the tool's. `Task`-typed
        (opaque) tools are exempt: they read `task.inputs` themselves.
        """
        if not self.opaque:
            accepted = {field.name for field in self.inputs}
            for task_input in task.inputs:
                if task_input.name not in accepted:
                    raise ToolBindingError(f"Tool '{self.name}' does not accept input '{task_input.name}', which the task declares.")

        kwargs: Dict[str, Any] = {}
        for name, hint in self._hints.items():
            if name == "return":
                continue
            unwrapped = _unwrap(hint)
            if unwrapped is Task:
                kwargs[name] = task
            elif unwrapped is ExecutionContext:
                kwargs[name] = context
            elif _is_param(hint):
                sig_param = self._signature.parameters[name]
                default = None if sig_param.default is inspect.Parameter.empty else sig_param.default
                kwargs[name] = task.get_param_value(name, default)
            else:
                kwargs[name] = self._bind_input(name, unwrapped, task)
        return kwargs

    def _bind_input(self, name: str, unwrapped: Any, task: Task) -> Any:
        sig_param = self._signature.parameters[name]
        has_default = sig_param.default is not inspect.Parameter.empty
        optional = has_default or _is_optional_type(unwrapped)
        default = sig_param.default if has_default else None

        task_input = task.get_input(name)
        value = task_input.value if task_input is not None else default

        if value is None and not optional and not self.opaque:
            get_from = task_input.get_from if task_input is not None else None
            mapping = f" (get_from='{get_from}')" if get_from else ""
            raise ToolBindingError(f"Tool '{self.name}' input '{name}' resolved to None{mapping}; a value is required.")

        return value

    def to_dict(self, agent_type: str) -> Dict[str, Any]:
        entry: Dict[str, Any] = {
            "name": self.name,
            "type": f"{agent_type}.{self.name}",
        }
        if self.description:
            entry["description"] = self.description
        if self.inputs:
            entry["inputs"] = [i.to_dict() for i in self.inputs]
        if self.params:
            entry["params"] = [p.to_dict() for p in self.params]
        if self.outputs:
            entry["outputs"] = self.outputs
        return entry
