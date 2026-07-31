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
from antikythera_agents.annotations import _ContextMarker
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


def _is_context(hint: Any) -> bool:
    metadata = getattr(hint, "__metadata__", None)
    return bool(metadata) and any(isinstance(m, _ContextMarker) for m in metadata)


def _is_optional_type(tp: Any) -> bool:
    return typing.get_origin(tp) is typing.Union and type(None) in typing.get_args(tp)


def _is_typeddict(tp: Any) -> bool:
    """True for a `TypedDict` class, as opposed to a plain `dict`/`Dict[str, Any]`.

    `__required_keys__`/`__optional_keys__` are set by the `TypedDict` metaclass on the
    class itself (not on instances), so checking for them distinguishes a real `TypedDict`
    from a bare `dict` without depending on `typing.is_typeddict`, which isn't available
    before Python 3.10.
    """
    return isinstance(tp, type) and hasattr(tp, "__required_keys__") and hasattr(tp, "__optional_keys__")


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
        """Task inputs: every parameter that isn't `Task`, `ExecutionContext`, `Param[T]` or
        `Context[T]`.

        Covers both an unannotated parameter and one explicitly marked `Input[T]` — the two
        bind identically, per ADR-0002.
        """
        fields = []
        for name, hint in self._hints.items():
            if name == "return":
                continue
            unwrapped = _unwrap(hint)
            if unwrapped is Task or unwrapped is ExecutionContext or _is_param(hint) or _is_context(hint):
                continue
            sig_param = self._signature.parameters[name]
            has_default = sig_param.default is not inspect.Parameter.empty
            fields.append(ToolField(name=name, type_hint=_type_hint_name(unwrapped), optional=has_default or _is_optional_type(unwrapped)))
        return fields

    @cached_property
    def requires_context(self) -> List[str]:
        """Names of the expansion-context keys this tool's `Context[T]` parameters need."""
        return [name for name, hint in self._hints.items() if name != "return" and _is_context(hint)]

    @cached_property
    def _output_typeddict(self) -> Optional[type]:
        """The tool's return type, if it's a `TypedDict`; `None` otherwise (issue-td-06).

        A bare `dict`/`Dict[str, Any]` return type, or no return annotation at all, yields
        `None` here — such a tool has nothing to check its output against and is exempt from
        output enforcement, same as an opaque (`Task`-typed) tool.
        """
        hint = self._hints.get("return")
        return hint if _is_typeddict(hint) else None

    @cached_property
    def outputs(self) -> List[ToolField]:
        typed_dict = self._output_typeddict
        if typed_dict is None:
            return []
        hints = typing.get_type_hints(typed_dict)
        return [ToolField(name=name, type_hint=_type_hint_name(hint), optional=name in typed_dict.__optional_keys__) for name, hint in hints.items()]

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
            elif _is_context(hint):
                kwargs[name] = self._bind_context(name, task)
            else:
                kwargs[name] = self._bind_input(name, unwrapped, task)
        return kwargs

    def _bind_context(self, name: str, task: Task) -> Any:
        sig_param = self._signature.parameters[name]
        has_default = sig_param.default is not inspect.Parameter.empty

        if name in task.context:
            return task.context[name]
        if has_default:
            return sig_param.default
        raise ToolBindingError(f"Tool '{self.name}' requires context key '{name}', which is absent from the task's context.")

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

    def validate_output(self, result: Dict[str, Any]) -> None:
        """Check a tool's returned dict against its declared `TypedDict` return type.

        The other half of strict binding (ADR-0002, issue-td-06): a key the `TypedDict`
        declares required but the tool didn't return currently gets persisted into session
        data as `None` as though it were a real result. Raises `ToolBindingError`, naming the
        key, before that can happen.

        Exempt, same as strict input binding: opaque (`Task`-typed) tools, and any tool whose
        return type isn't a `TypedDict` (a bare `dict`/`Dict[str, Any]`, or no annotation) —
        `system.composite` returns whatever outputs the blueprint declares and can never have
        a fixed return type, and stays opaque permanently.
        """
        if self.opaque or self._output_typeddict is None:
            return
        for field in self.outputs:
            if field.optional:
                continue
            if field.name not in result:
                raise ToolBindingError(f"Tool '{self.name}' output '{field.name}' is declared but missing from the returned dict.")

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
            entry["outputs"] = [o.to_dict() for o in self.outputs]
        if self.requires_context:
            entry["requires_context"] = self.requires_context
        return entry
