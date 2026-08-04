from __future__ import annotations

import inspect
import types
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
from antikythera_agents.typing_compat import get_type_hints as _typeddict_hints

# `types.UnionType` is the `A | B` union, new in Python 3.10; `None` on 3.9.
_UNION_TYPE = getattr(types, "UnionType", None)


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


def _is_union_type(tp: Any) -> bool:
    """True for both spellings of a union: `Union[A, B]`/`Optional[A]` and `A | B`.

    They are distinct objects before Python 3.14 (`typing.Union` vs `types.UnionType`) and
    the same object from 3.14 on, so both origins have to be accepted.
    """
    origin = typing.get_origin(tp)
    return origin is typing.Union or (_UNION_TYPE is not None and origin is _UNION_TYPE)


def _is_optional_type(tp: Any) -> bool:
    return _is_union_type(tp) and type(None) in typing.get_args(tp)


def _checkable_type(hint: Any) -> Optional[type]:
    """The plain class `hint` can be type-checked against, or `None` to skip checking.

    Only a plain class (`Frame`, `str`, ...) is checked (issue-td-07); a parameterised
    generic (`list[JointTrajectory]`, a `Union` of more than one non-`None` type, ...) is
    left alone. `Optional[X]` unwraps to `X` when `X` itself is a plain class — whether
    `None` is an acceptable value is decided elsewhere, by the existing None-handling rules;
    this only picks the type to check non-`None` values against.
    """
    # `Any` is the hint an unannotated parameter gets, and it accepts everything. It has to
    # be rejected explicitly: from Python 3.11 on it is a class, so `isinstance(hint, type)`
    # admits it, but `isinstance(value, Any)` then raises `TypeError`.
    if hint is Any:
        return None
    if isinstance(hint, type):
        return hint
    if _is_optional_type(hint):
        args = [a for a in typing.get_args(hint) if a is not type(None)]
        if len(args) == 1 and isinstance(args[0], type):
            return args[0]
    return None


def _type_matches(expected: type, value: Any) -> bool:
    """Whether `value` satisfies `expected`, lenient about the int/float widening that
    protobuf and `compas_pb` deserialisation can introduce.
    """
    if expected is float and isinstance(value, int):
        return True
    if expected is int and isinstance(value, float):
        return value.is_integer()
    return isinstance(value, expected)


def _is_typeddict(tp: Any) -> bool:
    """True for a `TypedDict` class, as opposed to a plain `dict`/`Dict[str, Any]`.

    `__required_keys__`/`__optional_keys__` are set by the `TypedDict` metaclass on the
    class itself (not on instances), so checking for them distinguishes a real `TypedDict`
    from a bare `dict` without depending on `typing.is_typeddict`, which isn't available
    before Python 3.10.
    """
    return isinstance(tp, type) and hasattr(tp, "__required_keys__") and hasattr(tp, "__optional_keys__")


def _type_hint_name(tp: Any) -> str:
    """A display name for `tp`, spelled the same way on every supported interpreter.

    Unions are rendered explicitly rather than via `repr`: Python 3.14 merged `typing.Union`
    into `types.UnionType`, so `str(Optional[int])` changed from `typing.Optional[int]` to
    `int | None`. These names reach the tool catalog and serialised blueprints, so they are
    pinned to the `Optional[...]`/`Union[...]` spelling regardless of how the annotation was
    written or which interpreter reads it.
    """
    if tp is type(None):
        return "None"
    # Pinned for the same reason: `typing.Any` became a class in 3.11, so the plain-class
    # branch below would render it as `typing.Any` there and `Any` on older interpreters.
    if tp is Any:
        return "Any"
    if _is_union_type(tp):
        args = typing.get_args(tp)
        present = [a for a in args if a is not type(None)]
        rendered = ", ".join(_type_hint_name(a) for a in present)
        if len(present) > 1:
            rendered = f"Union[{rendered}]"
        return f"Optional[{rendered}]" if len(present) != len(args) else rendered
    if isinstance(tp, type) and not typing.get_args(tp):
        return tp.__name__ if tp.__module__ == "builtins" else f"{tp.__module__}.{tp.__qualname__}"
    return str(tp).replace("typing.", "")


def _docstring_section_spans(lines: List[str]) -> Dict[str, "tuple[int, int]"]:
    """Locate each NumPydoc section's header name -> (content_start, content_end) line range.

    A section header is a line with no leading whitespace immediately followed by a line made
    up entirely of dashes. This is detected structurally, without a hardcoded list of NumPydoc
    section names, so it degrades to an empty dict rather than raising for anything that
    doesn't look like this shape (issue-td-08: a malformed docstring must still produce a
    usable, if description-less, catalog entry).
    """
    headers: List[Any] = []
    for i in range(len(lines) - 1):
        header = lines[i]
        if not header or header[0].isspace():
            continue
        name = header.strip()
        if not name:
            continue
        underline = lines[i + 1].strip()
        if underline and set(underline) == {"-"}:
            headers.append((name, i))

    spans: Dict[str, "tuple[int, int]"] = {}
    for idx, (name, header_idx) in enumerate(headers):
        content_start = header_idx + 2
        content_end = headers[idx + 1][1] if idx + 1 < len(headers) else len(lines)
        spans[name] = (content_start, content_end)
    return spans


def _parse_field_list(lines: List[str], start: int, end: int) -> Dict[str, str]:
    """Parse a NumPydoc field list — the body of a `Parameters`/`Returns` section — by hand.

    Each field starts at a line with no leading whitespace (`name` or `name : type`);
    subsequent indented lines are its (possibly multi-line) description, joined on a single
    space. Anything that doesn't fit this shape (a stray blank line, a description-only block
    with no field header) is silently skipped rather than raising.
    """
    fields: Dict[str, str] = {}
    current_names: List[str] = []
    current_desc: List[str] = []

    def flush() -> None:
        if current_names and current_desc:
            text = " ".join(" ".join(current_desc).split())
            for field_name in current_names:
                fields[field_name] = text

    for i in range(start, end):
        line = lines[i]
        if not line.strip():
            continue
        if not line[0].isspace():
            flush()
            current_desc = []
            name_part = line.split(":", 1)[0].strip()
            current_names = [n.strip() for n in name_part.split(",") if n.strip()]
        else:
            current_desc.append(line.strip())
    flush()
    return fields


def _parse_numpy_docstring(doc: Optional[str]) -> "tuple[Dict[str, str], Dict[str, str]]":
    """Parameter and return descriptions parsed from a NumPy-style docstring (issue-td-08).

    Returns `(param_descriptions, return_descriptions)`, both `{name: description}`. Written
    by hand rather than adding a dependency, per the issue — the sections are simple. Must
    degrade rather than fail: no docstring, no `Parameters`/`Returns` section, or a malformed
    block all yield an empty dict for the affected side, never an exception.
    """
    if not doc:
        return {}, {}
    lines = doc.splitlines()
    spans = _docstring_section_spans(lines)

    params: Dict[str, str] = {}
    if "Parameters" in spans:
        start, end = spans["Parameters"]
        params = _parse_field_list(lines, start, end)

    returns: Dict[str, str] = {}
    if "Returns" in spans:
        start, end = spans["Returns"]
        returns = _parse_field_list(lines, start, end)

    return params, returns


@dataclass(frozen=True)
class ToolField:
    """A single named, typed, optionally-optional field — shape shared by inputs and params."""

    name: str
    type_hint: str
    optional: bool
    description: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        entry: Dict[str, Any] = {"name": self.name, "type_hint": self.type_hint, "optional": self.optional}
        if self.description:
            entry["description"] = self.description
        return entry


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
    def _parameters(self) -> Dict[str, Any]:
        """The tool's bindable parameters, in signature order, each mapped to its type hint.

        Driven by the signature rather than by `_hints`, which reports only the *annotated*
        names: an unannotated parameter is a task input (ADR-0002, and see `inputs`), so
        taking `_hints` as the parameter list would drop it from the catalog and from `bind`
        — the task would then be told the tool "does not accept" an input it in fact
        requires, or the tool would be called without it. Such a parameter gets `Any`, which
        binds like any other input but is exempt from type checking.

        `self` and any `*args`/`**kwargs` are not bindable from a task and are excluded.
        """
        hints = self._hints
        parameters: Dict[str, Any] = {}
        for index, (name, sig_param) in enumerate(self._signature.parameters.items()):
            if index == 0 and name in ("self", "cls"):
                continue
            if sig_param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue
            parameters[name] = hints.get(name, Any)
        return parameters

    @cached_property
    def opaque(self) -> bool:
        """True for a tool that takes `Task` directly — no derivable inputs or outputs."""
        return any(_unwrap(hint) is Task for hint in self._parameters.values())

    @cached_property
    def description(self) -> Optional[str]:
        doc = inspect.getdoc(self.func)
        if not doc:
            return None
        summary = doc.strip().split("\n\n")[0]
        return " ".join(summary.split())

    @cached_property
    def _field_descriptions(self) -> "tuple[Dict[str, str], Dict[str, str]]":
        """`(param_descriptions, return_descriptions)` parsed from the tool's docstring."""
        return _parse_numpy_docstring(inspect.getdoc(self.func))

    @cached_property
    def params(self) -> List[ToolField]:
        param_docs, _ = self._field_descriptions
        fields = []
        for name, hint in self._parameters.items():
            if not _is_param(hint):
                continue
            inner = _unwrap(hint)
            sig_param = self._signature.parameters[name]
            has_default = sig_param.default is not inspect.Parameter.empty
            fields.append(
                ToolField(
                    name=name,
                    type_hint=_type_hint_name(inner),
                    optional=has_default or _is_optional_type(inner),
                    description=param_docs.get(name),
                )
            )
        return fields

    @cached_property
    def inputs(self) -> List[ToolField]:
        """Task inputs: every parameter that isn't `Task`, `ExecutionContext`, `Param[T]` or
        `Context[T]`.

        Covers both an unannotated parameter and one explicitly marked `Input[T]` — the two
        bind identically, per ADR-0002. An unannotated one is listed with the type hint
        `Any` (see `_parameters`).
        """
        param_docs, _ = self._field_descriptions
        fields = []
        for name, hint in self._parameters.items():
            unwrapped = _unwrap(hint)
            if unwrapped is Task or unwrapped is ExecutionContext or _is_param(hint) or _is_context(hint):
                continue
            sig_param = self._signature.parameters[name]
            has_default = sig_param.default is not inspect.Parameter.empty
            fields.append(
                ToolField(
                    name=name,
                    type_hint=_type_hint_name(unwrapped),
                    optional=has_default or _is_optional_type(unwrapped),
                    description=param_docs.get(name),
                )
            )
        return fields

    @cached_property
    def requires_context(self) -> List[str]:
        """Names of the expansion-context keys this tool's `Context[T]` parameters need."""
        return [name for name, hint in self._parameters.items() if _is_context(hint)]

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
        _, return_docs = self._field_descriptions
        # Not `typing.get_type_hints`: before 3.11 only the `typing_extensions` version
        # strips a backported `NotRequired[...]` off the annotation (see `typing_compat`).
        hints = _typeddict_hints(typed_dict)
        return [
            ToolField(
                name=name,
                type_hint=_type_hint_name(hint),
                optional=name in typed_dict.__optional_keys__,
                description=return_docs.get(name),
            )
            for name, hint in hints.items()
        ]

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
        for name, hint in self._parameters.items():
            unwrapped = _unwrap(hint)
            if unwrapped is Task:
                kwargs[name] = task
            elif unwrapped is ExecutionContext:
                kwargs[name] = context
            elif _is_param(hint):
                sig_param = self._signature.parameters[name]
                default = None if sig_param.default is inspect.Parameter.empty else sig_param.default
                value = task.get_param_value(name, default)
                self._check_type(name, unwrapped, value)
                kwargs[name] = value
            elif _is_context(hint):
                kwargs[name] = self._bind_context(name, unwrapped, task)
            else:
                kwargs[name] = self._bind_input(name, unwrapped, task)
        return kwargs

    def _check_type(self, name: str, hint: Any, value: Any) -> None:
        """Check a bound value against a plain-class annotation (issue-td-07).

        A no-op for opaque tools, for `None` (whether `None` is acceptable here was already
        decided by the caller's own None-handling), and for any hint that isn't a plain class
        (`_checkable_type` returns `None`).
        """
        if self.opaque or value is None:
            return
        expected = _checkable_type(hint)
        if expected is None:
            return
        if not _type_matches(expected, value):
            raise ToolBindingError(f"Tool '{self.name}' argument '{name}' expected {_type_hint_name(expected)}, got {_type_hint_name(type(value))}.")

    def _bind_context(self, name: str, hint: Any, task: Task) -> Any:
        sig_param = self._signature.parameters[name]
        has_default = sig_param.default is not inspect.Parameter.empty

        if name in task.context:
            value = task.context[name]
        elif has_default:
            return sig_param.default
        else:
            raise ToolBindingError(f"Tool '{self.name}' requires context key '{name}', which is absent from the task's context.")

        self._check_type(name, hint, value)
        return value

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

        self._check_type(name, unwrapped, value)
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
