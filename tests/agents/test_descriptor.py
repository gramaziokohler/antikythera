from __future__ import annotations

import typing
from typing import Optional

import pytest

from antikythera.models import Task
from antikythera.models import TaskInput
from antikythera_agents.annotations import Input
from antikythera_agents.annotations import Param
from antikythera_agents.context import ExecutionContext
from antikythera_agents.decorators import tool
from antikythera_agents.descriptor import ToolBindingError


def test_param_importable_and_subscriptable():
    hints = typing.get_type_hints(lambda x: x, include_extras=True)  # sanity: get_type_hints works at all
    assert hints == {}

    annotated = Param[int]
    assert typing.get_origin(annotated) is typing.Annotated
    assert annotated.__origin__ is int


def test_descriptor_exposes_name_description_params_and_outputs():
    @tool(name="greet")
    def greet(self, name_prefix: Param[str] = "Hello") -> dict:
        """Greet someone.

        Longer explanation that should not be part of the summary.
        """
        return {}

    descriptor = greet._descriptor

    assert descriptor.name == "greet"
    assert descriptor.description == "Greet someone."
    assert [p.name for p in descriptor.params] == ["name_prefix"]
    assert descriptor.params[0].type_hint == "str"
    assert descriptor.params[0].optional is True
    assert descriptor.outputs == []


def test_param_without_default_is_not_optional():
    @tool(name="scale")
    def scale(self, factor: Param[float]) -> dict:
        return {}

    (field,) = scale._descriptor.params
    assert field.optional is False


def test_task_annotated_tool_is_opaque():
    @tool(name="opaque_tool")
    def opaque_tool(self, task: Task) -> dict:
        return {}

    descriptor = opaque_tool._descriptor
    assert descriptor.opaque is True


def test_non_task_tool_is_not_opaque():
    @tool(name="transparent_tool")
    def transparent_tool(self, count: Param[int] = 1) -> dict:
        return {}

    assert transparent_tool._descriptor.opaque is False


def test_hints_resolve_lazily_and_are_cached():
    @tool(name="forward_ref_tool")
    def forward_ref_tool(self, task: Task, note: "NotYetDefined" = None) -> dict:  # noqa: F821
        return {}

    descriptor = forward_ref_tool._descriptor

    # Decoration succeeded even though `NotYetDefined` doesn't exist yet, and the first
    # access fails lazily rather than at decoration/import time.
    with pytest.raises(NameError):
        descriptor.params

    globals()["NotYetDefined"] = str
    try:
        # Now resolvable; also proves the failed first attempt wasn't wrongly cached.
        assert descriptor.params == []
        assert descriptor.opaque is True

        call_count = 0
        real_get_type_hints = typing.get_type_hints

        def counting_get_type_hints(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return real_get_type_hints(*args, **kwargs)

        # A fresh descriptor to observe caching in isolation from the calls above.
        @tool(name="cached_tool")
        def cached_tool(self, task: Task) -> dict:
            return {}

        cached_descriptor = cached_tool._descriptor
        typing.get_type_hints = counting_get_type_hints
        try:
            cached_descriptor.opaque
            cached_descriptor.params
            cached_descriptor.description
        finally:
            typing.get_type_hints = real_get_type_hints

        assert call_count == 1
    finally:
        del globals()["NotYetDefined"]


def test_to_dict_omits_empty_sections_and_includes_type():
    @tool(name="sleep")
    def sleep_process(self, task: Task, duration: Param[float] = 1) -> dict:
        return {}

    entry = sleep_process._descriptor.to_dict(agent_type="system")

    assert entry == {
        "name": "sleep",
        "type": "system.sleep",
        "params": [{"name": "duration", "type_hint": "float", "optional": True}],
    }


def test_to_dict_opaque_tool_has_no_input_or_output_detail():
    @tool(name="start")
    def start_process(self, task: Task) -> dict:
        """Start the process."""
        return {}

    entry = start_process._descriptor.to_dict(agent_type="system")

    assert entry == {"name": "start", "type": "system.start", "description": "Start the process."}


def test_bind_supplies_task_and_context():
    @tool(name="ctx_tool")
    def ctx_tool(self, task: Task, context: ExecutionContext) -> dict:
        return {}

    descriptor = ctx_tool._descriptor
    task = Task(id="t1", type="test.ctx_tool")
    context = ExecutionContext()

    kwargs = descriptor.bind(task=task, context=context)

    assert kwargs == {"task": task, "context": context}


def test_bind_supplies_param_value_with_fallback_default():
    from antikythera.models import TaskParam

    @tool(name="sleep")
    def sleep_process(self, task: Task, duration: Param[float] = 1) -> dict:
        return {}

    descriptor = sleep_process._descriptor

    task_with_param = Task(id="t1", type="test.sleep", params=[TaskParam(name="duration", value=3)])
    assert descriptor.bind(task=task_with_param, context=None) == {"task": task_with_param, "duration": 3}

    task_without_param = Task(id="t2", type="test.sleep")
    assert descriptor.bind(task=task_without_param, context=None) == {"task": task_without_param, "duration": 1}


def test_unannotated_parameter_binds_to_task_input():
    @tool(name="needs_input")
    def needs_input(self, thing: str) -> dict:
        return {}

    descriptor = needs_input._descriptor
    task = Task(id="t1", type="test.needs_input", inputs=[TaskInput(name="thing", value="a value")])

    assert descriptor.bind(task=task, context=None) == {"thing": "a value"}


def test_input_marker_binds_identically_to_unannotated():
    @tool(name="needs_input")
    def needs_input(self, thing: Input[str]) -> dict:
        return {}

    descriptor = needs_input._descriptor
    assert [f.name for f in descriptor.inputs] == ["thing"]

    task = Task(id="t1", type="test.needs_input", inputs=[TaskInput(name="thing", value="a value")])
    assert descriptor.bind(task=task, context=None) == {"thing": "a value"}


def test_bind_fails_when_required_input_missing():
    @tool(name="needs_input")
    def needs_input(self, thing: str) -> dict:
        return {}

    descriptor = needs_input._descriptor
    task = Task(id="t1", type="test.needs_input")

    with pytest.raises(ToolBindingError, match="thing"):
        descriptor.bind(task=task, context=None)


def test_bind_fails_on_input_the_tool_does_not_accept():
    @tool(name="needs_input")
    def needs_input(self, thing: str) -> dict:
        return {}

    descriptor = needs_input._descriptor
    task = Task(id="t1", type="test.needs_input", inputs=[TaskInput(name="thing", value="ok"), TaskInput(name="extra", value="surprise")])

    with pytest.raises(ToolBindingError, match="extra"):
        descriptor.bind(task=task, context=None)


def test_bind_fails_when_non_optional_input_resolves_to_none_and_names_get_from():
    @tool(name="needs_input")
    def needs_input(self, thing: str) -> dict:
        return {}

    descriptor = needs_input._descriptor
    task = Task(id="t1", type="test.needs_input", inputs=[TaskInput(name="thing", value=None, get_from="upstream_key")])

    with pytest.raises(ToolBindingError, match="thing") as exc_info:
        descriptor.bind(task=task, context=None)
    assert "upstream_key" in str(exc_info.value)


def test_bind_accepts_none_for_optional_or_defaulted_input():
    @tool(name="needs_input")
    def needs_input(self, thing: Optional[str] = None, other: str = "fallback") -> dict:
        return {}

    descriptor = needs_input._descriptor
    task = Task(id="t1", type="test.needs_input", inputs=[TaskInput(name="thing", value=None), TaskInput(name="other", value=None)])

    assert descriptor.bind(task=task, context=None) == {"thing": None, "other": None}

    task_without_inputs = Task(id="t2", type="test.needs_input")
    assert descriptor.bind(task=task_without_inputs, context=None) == {"thing": None, "other": "fallback"}


def test_bind_uses_static_literal_input_value():
    @tool(name="needs_input")
    def needs_input(self, thing: str) -> dict:
        return {}

    descriptor = needs_input._descriptor
    task = Task(id="t1", type="test.needs_input", inputs=[TaskInput(name="thing", value="a literal")])

    assert descriptor.bind(task=task, context=None) == {"thing": "a literal"}


def test_task_annotated_tool_exempt_from_strict_input_binding():
    @tool(name="opaque_tool")
    def opaque_tool(self, task: Task) -> dict:
        return {}

    descriptor = opaque_tool._descriptor
    # An input the (opaque) tool never declares does not trip the strict binder.
    task = Task(id="t1", type="test.opaque_tool", inputs=[TaskInput(name="anything", value="ignored")])

    assert descriptor.bind(task=task, context=None) == {"task": task}


def test_inputs_listed_with_type_hint_and_optionality():
    @tool(name="needs_input")
    def needs_input(self, thing: str, extra: Optional[int] = None) -> dict:
        return {}

    descriptor = needs_input._descriptor

    assert {f.name: (f.type_hint, f.optional) for f in descriptor.inputs} == {
        "thing": ("str", False),
        "extra": ("Optional[int]", True),
    }
