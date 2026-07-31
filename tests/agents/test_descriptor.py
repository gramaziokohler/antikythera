from __future__ import annotations

import typing
from datetime import datetime
from typing import List
from typing import NotRequired
from typing import Optional
from typing import TypedDict

import pytest
from compas.geometry import Frame
from compas_pb import pb_dump_bts
from compas_pb import pb_load_bts

from antikythera.models import Task
from antikythera.models import TaskAssignmentMessage
from antikythera.models import TaskInput
from antikythera.models import TaskParam
from antikythera.models.conversions import dict_to_inputs
from antikythera.models.conversions import dict_to_params
from antikythera_agents.annotations import Context
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


def test_context_binds_matching_key_from_task_context():
    @tool(name="process_element")
    def process_element(self, element_id: Context[str]) -> dict:
        return {}

    descriptor = process_element._descriptor
    task = Task(id="t1", type="test.process_element", context={"element_id": "guid-123"})

    assert descriptor.bind(task=task, context=None) == {"element_id": "guid-123"}


def test_context_not_listed_as_task_input():
    @tool(name="process_element")
    def process_element(self, element_id: Context[str]) -> dict:
        return {}

    descriptor = process_element._descriptor
    assert descriptor.inputs == []


def test_context_missing_key_raises_tool_binding_error_naming_key():
    @tool(name="process_element")
    def process_element(self, element_id: Context[str]) -> dict:
        return {}

    descriptor = process_element._descriptor
    task = Task(id="t1", type="test.process_element", context={})

    with pytest.raises(ToolBindingError, match="element_id"):
        descriptor.bind(task=task, context=None)


def test_context_with_default_falls_back_when_key_absent():
    @tool(name="process_element")
    def process_element(self, element_id: Context[str] = "fallback") -> dict:
        return {}

    descriptor = process_element._descriptor
    task = Task(id="t1", type="test.process_element", context={})

    assert descriptor.bind(task=task, context=None) == {"element_id": "fallback"}


def test_context_and_execution_context_coexist_and_bind_correctly():
    @tool(name="process_element")
    def process_element(self, task: Task, element_id: Context[str], context: ExecutionContext) -> dict:
        return {}

    descriptor = process_element._descriptor
    task = Task(id="t1", type="test.process_element", context={"element_id": "guid-456"})
    exec_context = ExecutionContext()

    assert descriptor.bind(task=task, context=exec_context) == {
        "task": task,
        "element_id": "guid-456",
        "context": exec_context,
    }


def test_requires_context_reported_in_catalog():
    @tool(name="process_element")
    def process_element(self, element_id: Context[str]) -> dict:
        return {}

    entry = process_element._descriptor.to_dict(agent_type="test_dynamic")

    assert entry == {
        "name": "process_element",
        "type": "test_dynamic.process_element",
        "requires_context": ["element_id"],
    }


CopyResult = TypedDict("CopyResult", {"copied_files": list, "destination": NotRequired[str]})


def test_typeddict_return_type_is_derived_into_outputs():
    @tool(name="copy")
    def copy_file(self, source: str) -> CopyResult:
        return {"copied_files": []}

    descriptor = copy_file._descriptor

    assert {f.name: (f.type_hint, f.optional) for f in descriptor.outputs} == {
        "copied_files": ("list", False),
        "destination": ("str", True),
    }


def test_to_dict_marks_notrequired_outputs_optional_and_others_not():
    @tool(name="copy")
    def copy_file(self, source: str) -> CopyResult:
        return {"copied_files": []}

    entry = copy_file._descriptor.to_dict(agent_type="io")

    assert entry["outputs"] == [
        {"name": "copied_files", "type_hint": "list", "optional": False},
        {"name": "destination", "type_hint": "str", "optional": True},
    ]


def test_validate_output_raises_when_required_key_missing():
    @tool(name="copy")
    def copy_file(self, source: str) -> CopyResult:
        return {}

    descriptor = copy_file._descriptor

    with pytest.raises(ToolBindingError, match="copied_files"):
        descriptor.validate_output({})


def test_validate_output_accepts_missing_notrequired_key():
    @tool(name="copy")
    def copy_file(self, source: str) -> CopyResult:
        return {"copied_files": []}

    descriptor = copy_file._descriptor

    descriptor.validate_output({"copied_files": ["a.txt"]})


def test_validate_output_passes_when_all_required_keys_present():
    @tool(name="copy")
    def copy_file(self, source: str) -> CopyResult:
        return {"copied_files": []}

    descriptor = copy_file._descriptor

    descriptor.validate_output({"copied_files": ["a.txt"], "destination": "/tmp"})


def test_plain_dict_return_type_is_exempt_from_output_detail_and_validation():
    @tool(name="transparent_tool")
    def transparent_tool(self, count: Param[int] = 1) -> dict:
        return {}

    descriptor = transparent_tool._descriptor

    assert descriptor.outputs == []
    entry = descriptor.to_dict(agent_type="test")
    assert "outputs" not in entry

    # A key nobody declared, or a missing key: nothing to check against, so no error.
    descriptor.validate_output({"whatever": "unchecked"})


def test_task_annotated_tool_with_typeddict_return_is_still_opaque_and_exempt():
    @tool(name="opaque_tool")
    def opaque_tool(self, task: Task) -> CopyResult:
        return {}

    descriptor = opaque_tool._descriptor

    assert descriptor.opaque is True
    descriptor.validate_output({})


# --- issue-td-07: type checking at bind time for plain-class annotations ---


def test_bind_fails_when_input_type_mismatches_plain_class_annotation():
    @tool(name="needs_frame")
    def needs_frame(self, frame: Frame) -> dict:
        return {}

    descriptor = needs_frame._descriptor
    task = Task(id="t1", type="test.needs_frame", inputs=[TaskInput(name="frame", value="not a frame")])

    with pytest.raises(ToolBindingError, match="frame") as exc_info:
        descriptor.bind(task=task, context=None)
    message = str(exc_info.value)
    assert "Frame" in message
    assert "str" in message


def test_bind_skips_check_for_parameterised_generic_annotation():
    @tool(name="needs_list")
    def needs_list(self, items: List[int]) -> dict:
        return {}

    descriptor = needs_list._descriptor
    # Element types are not checked - the annotation is a generic, so the mismatch is ignored.
    task = Task(id="t1", type="test.needs_list", inputs=[TaskInput(name="items", value=["not", "ints"])])

    assert descriptor.bind(task=task, context=None) == {"items": ["not", "ints"]}


def test_bind_accepts_int_for_float_input_and_integral_float_for_int_input():
    @tool(name="needs_numbers")
    def needs_numbers(self, as_float: float, as_int: int) -> dict:
        return {}

    descriptor = needs_numbers._descriptor
    task = Task(id="t1", type="test.needs_numbers", inputs=[TaskInput(name="as_float", value=5), TaskInput(name="as_int", value=5.0)])

    assert descriptor.bind(task=task, context=None) == {"as_float": 5, "as_int": 5.0}


def test_bind_fails_on_non_integral_float_for_int_annotation():
    @tool(name="needs_int")
    def needs_int(self, count: int) -> dict:
        return {}

    descriptor = needs_int._descriptor
    task = Task(id="t1", type="test.needs_int", inputs=[TaskInput(name="count", value=5.5)])

    with pytest.raises(ToolBindingError, match="count"):
        descriptor.bind(task=task, context=None)


def test_bind_accepts_int_for_float_param_and_integral_float_for_int_param():
    @tool(name="needs_number_params")
    def needs_number_params(self, as_float: Param[float] = 1.0, as_int: Param[int] = 1) -> dict:
        return {}

    descriptor = needs_number_params._descriptor
    task = Task(
        id="t1",
        type="test.needs_number_params",
        params=[TaskParam(name="as_float", value=5), TaskParam(name="as_int", value=5.0)],
    )

    assert descriptor.bind(task=task, context=None) == {"as_float": 5, "as_int": 5.0}


def test_bind_fails_when_param_type_mismatches_plain_class_annotation():
    @tool(name="needs_str_param")
    def needs_str_param(self, name: Param[str] = "x") -> dict:
        return {}

    descriptor = needs_str_param._descriptor
    task = Task(id="t1", type="test.needs_str_param", params=[TaskParam(name="name", value=42)])

    with pytest.raises(ToolBindingError, match="name"):
        descriptor.bind(task=task, context=None)


def test_bind_fails_when_context_type_mismatches_plain_class_annotation():
    @tool(name="needs_context")
    def needs_context(self, element_id: Context[int]) -> dict:
        return {}

    descriptor = needs_context._descriptor
    task = Task(id="t1", type="test.needs_context", context={"element_id": "not-an-int"})

    with pytest.raises(ToolBindingError, match="element_id"):
        descriptor.bind(task=task, context=None)


def test_bind_none_handling_unchanged_by_type_check():
    @tool(name="optional_frame")
    def optional_frame(self, frame: Optional[Frame] = None) -> dict:
        return {}

    descriptor = optional_frame._descriptor
    task = Task(id="t1", type="test.optional_frame")

    # No value supplied for an optional input - still resolves to None, not a type error.
    assert descriptor.bind(task=task, context=None) == {"frame": None}


def test_task_annotated_tool_exempt_from_type_check():
    @tool(name="opaque_tool")
    def opaque_tool(self, task: Task, count: Param[int] = 1) -> dict:
        return {}

    descriptor = opaque_tool._descriptor
    task = Task(id="t1", type="test.opaque_tool", params=[TaskParam(name="count", value="not an int")])

    assert descriptor.bind(task=task, context=None) == {"task": task, "count": "not an int"}


def test_protobuf_round_trip_of_each_supported_value_kind_binds_without_error():
    """A round trip through the wire format (issue-td-07's last acceptance criterion).

    `compas_pb.core.primitive_to_pb`/`primitive_from_pb` widen every Python `int` to a
    protobuf double on the wire, then narrow any integral double back to `int` on the way
    back - so both an originally-int and an originally-float numeric value can come back as
    either Python type. A tool's plain `int`/`float` annotations must accept both.
    """

    @tool(name="round_trip_tool")
    def round_trip_tool(self, an_int: int, an_integral_float: float, a_float: float, a_str: str, a_bool: bool, a_frame: Frame) -> dict:
        return {}

    inputs = {
        "an_int": 5,
        "an_integral_float": 3.0,
        "a_float": 3.14,
        "a_str": "hello",
        "a_bool": True,
        "a_frame": Frame.worldXY(),
    }
    message = TaskAssignmentMessage(id="t1", type="test.round_trip_tool", inputs=inputs, timestamp=datetime.now())
    pb2 = pb_load_bts(pb_dump_bts(message))
    round_tripped = dict(pb2.inputs)

    descriptor = round_trip_tool._descriptor
    task = Task(id="t1", type="test.round_trip_tool", inputs=dict_to_inputs(round_tripped))

    kwargs = descriptor.bind(task=task, context=None)
    assert kwargs["a_str"] == "hello"
    assert kwargs["a_bool"] is True
    assert isinstance(kwargs["a_frame"], Frame)


# --- issue-td-08: per-field descriptions parsed from NumPy docstrings ---

DescribedResult = TypedDict("DescribedResult", {"value": int, "extra": NotRequired[str]})


def test_param_and_input_descriptions_parsed_from_numpy_docstring():
    @tool(name="described")
    def described(self, count: Param[int] = 1, name: str = "x") -> dict:
        """Do something.

        Parameters
        ----------
        count : int
            How many times to do it.
        name : str
            What to call it.
        """
        return {}

    descriptor = described._descriptor

    assert descriptor.params[0].description == "How many times to do it."
    assert descriptor.inputs[0].description == "What to call it."


def test_tool_level_description_stays_the_docstring_summary():
    @tool(name="described")
    def described(self, count: Param[int] = 1) -> dict:
        """Do something.

        Longer explanation that is not part of the summary.

        Parameters
        ----------
        count : int
            How many times to do it.
        """
        return {}

    descriptor = described._descriptor

    assert descriptor.description == "Do something."
    assert descriptor.params[0].description == "How many times to do it."


def test_return_values_documented_in_returns_section_populate_output_descriptions():
    @tool(name="described")
    def described(self, count: Param[int] = 1) -> DescribedResult:
        """Do something.

        Returns
        -------
        value : int
            The computed value.
        extra : str
            Some extra detail.
        """
        return {"value": 1}

    descriptor = described._descriptor

    assert {f.name: f.description for f in descriptor.outputs} == {
        "value": "The computed value.",
        "extra": "Some extra detail.",
    }


def test_no_docstring_yields_no_field_descriptions_without_error():
    @tool(name="undocumented")
    def undocumented(self, count: Param[int] = 1, thing: str = "x") -> DescribedResult:
        return {"value": 1}

    descriptor = undocumented._descriptor

    assert descriptor.params[0].description is None
    assert descriptor.inputs[0].description is None
    assert all(f.description is None for f in descriptor.outputs)

    entry = descriptor.to_dict(agent_type="test")
    assert "description" not in entry["params"][0]
    assert "description" not in entry["inputs"][0]
    assert all("description" not in o for o in entry["outputs"])


def test_docstring_with_no_parameters_section_yields_no_descriptions():
    @tool(name="described")
    def described(self, count: Param[int] = 1) -> dict:
        """Just a summary, no sections at all."""
        return {}

    descriptor = described._descriptor
    assert descriptor.params[0].description is None


def test_malformed_docstring_produces_catalog_entry_with_no_descriptions_and_no_error():
    @tool(name="described")
    def described(self, count: Param[int] = 1) -> dict:
        """Summary.

        Parameters
        --
        this is not a properly formatted field header
        count weird formatting no colon no indentation
        """
        return {}

    descriptor = described._descriptor

    entry = descriptor.to_dict(agent_type="test")
    assert entry["name"] == "described"
    assert descriptor.params[0].description is None


def test_documented_parameter_not_in_signature_is_ignored():
    @tool(name="described")
    def described(self, count: Param[int] = 1) -> dict:
        """Do something.

        Parameters
        ----------
        count : int
            How many times to do it.
        ghost : str
            Not a real parameter.
        """
        return {}

    descriptor = described._descriptor

    assert [f.name for f in descriptor.params] == ["count"]
    assert descriptor.params[0].description == "How many times to do it."


def test_parameter_absent_from_docstring_has_no_description_siblings_keep_theirs():
    @tool(name="described")
    def described(self, count: Param[int] = 1, name: str = "x") -> dict:
        """Do something.

        Parameters
        ----------
        count : int
            How many times to do it.
        """
        return {}

    descriptor = described._descriptor

    assert descriptor.params[0].description == "How many times to do it."
    assert descriptor.inputs[0].description is None


def test_multiline_description_is_captured():
    @tool(name="described")
    def described(self, count: Param[int] = 1) -> dict:
        """Do something.

        Parameters
        ----------
        count : int
            How many times to do it, spanning
            multiple lines of prose that should
            all be joined together.
        """
        return {}

    descriptor = described._descriptor

    assert descriptor.params[0].description == "How many times to do it, spanning multiple lines of prose that should all be joined together."


def test_to_dict_includes_field_descriptions():
    @tool(name="copy_like")
    def copy_like(self, source: str) -> DescribedResult:
        """Copy things.

        Parameters
        ----------
        source : str
            Glob pattern for the files to copy.

        Returns
        -------
        value : int
            The computed value.
        """
        return {"value": 1}

    entry = copy_like._descriptor.to_dict(agent_type="io")

    assert entry["inputs"] == [{"name": "source", "type_hint": "str", "optional": False, "description": "Glob pattern for the files to copy."}]
    assert entry["outputs"][0]["description"] == "The computed value."


def test_protobuf_round_trip_of_params_binds_without_error():
    @tool(name="round_trip_params_tool")
    def round_trip_params_tool(self, an_int: Param[int] = 0, a_float: Param[float] = 0.0) -> dict:
        return {}

    message = TaskAssignmentMessage(id="t1", type="test.round_trip_params_tool", params={"an_int": 5, "a_float": 3.0}, timestamp=datetime.now())
    pb2 = pb_load_bts(pb_dump_bts(message))
    round_tripped = dict(pb2.params)

    descriptor = round_trip_params_tool._descriptor
    task = Task(id="t1", type="test.round_trip_params_tool", params=dict_to_params(round_tripped))

    descriptor.bind(task=task, context=None)
