from unittest.mock import patch

import pytest

from antikythera.models import Task
from antikythera.models import TaskInput
from antikythera.models import TaskParam
from antikythera_actors.context import ExecutionContext
from antikythera_actors.decorators import get_actor_class
from antikythera_actors.decorators import list_registered_actors
from antikythera_actors.descriptor import ToolBindingError
from antikythera_actors.reference_actor import ReferenceActor


@pytest.fixture
def reference_actor():
    return ReferenceActor()


def test_reference_actor_is_registered_and_discoverable():
    assert list_registered_actors()["reference"] is ReferenceActor
    assert get_actor_class("reference") is ReferenceActor


def test_assemble_catalog_entry_covers_every_annotation_kind():
    """`describe`'s worth: the catalog entry for `assemble` reports every input, param,
    context requirement and output the tool declares, with descriptions parsed from its
    docstring (issue-td-10's acceptance criterion on the catalog).
    """
    entry = ReferenceActor.assemble._descriptor.to_dict("reference")

    assert entry["type"] == "reference.assemble"
    inputs = {i["name"]: i for i in entry["inputs"]}
    assert inputs["title"] == {"name": "title", "type_hint": "str", "optional": False, "description": inputs["title"]["description"]}
    assert inputs["title"]["description"]
    assert inputs["subtitle"]["optional"] is False
    assert inputs["note"]["optional"] is True

    params = {p["name"]: p for p in entry["params"]}
    assert params["tag"]["optional"] is False
    assert params["repeat"]["optional"] is True

    assert entry["requires_context"] == ["element_id"]

    outputs = {o["name"]: o for o in entry["outputs"]}
    assert outputs["message"]["optional"] is False
    assert outputs["detail"]["optional"] is True
    assert all(o["description"] for o in outputs.values())


def test_assemble_binds_every_annotation_kind_and_fills_optional_output(reference_actor):
    task = Task(
        id="assemble_task",
        type="reference.assemble",
        inputs=[
            TaskInput(name="title", value="Antikythera"),
            TaskInput(name="subtitle", value="Reference Actor Demo"),
            TaskInput(name="note", value="a note"),
        ],
        params=[TaskParam(name="tag", value="demo"), TaskParam(name="repeat", value=2)],
        context={"element_id": "element-1"},
    )

    result = reference_actor.execute_task(task)

    assert result["message"].count("element-1") == 2
    assert result["detail"] == "a note"


def test_assemble_context_falls_back_to_default_outside_dynamic_expansion(reference_actor):
    task = Task(
        id="assemble_task",
        type="reference.assemble",
        inputs=[TaskInput(name="title", value="A"), TaskInput(name="subtitle", value="B")],
        params=[TaskParam(name="tag", value="demo")],
    )

    result = reference_actor.execute_task(task)

    assert "unassigned" in result["message"]
    assert "detail" not in result


def test_assemble_missing_required_input_raises_binding_error(reference_actor):
    task = Task(
        id="assemble_task",
        type="reference.assemble",
        inputs=[TaskInput(name="title", value="A")],
        params=[TaskParam(name="tag", value="demo")],
    )

    with pytest.raises(ToolBindingError, match="subtitle"):
        reference_actor.execute_task(task)


def test_assemble_unexpected_input_raises_binding_error(reference_actor):
    task = Task(
        id="assemble_task",
        type="reference.assemble",
        inputs=[
            TaskInput(name="title", value="A"),
            TaskInput(name="subtitle", value="B"),
            TaskInput(name="bogus", value="nope"),
        ],
        params=[TaskParam(name="tag", value="demo")],
    )

    with pytest.raises(ToolBindingError, match="bogus"):
        reference_actor.execute_task(task)


def test_assemble_unresolved_none_input_raises_binding_error(reference_actor):
    """A `get_from`-mapped input that never resolved to a value (unavailable upstream) is a
    non-optional `None`, distinct from the input being absent entirely.
    """
    task = Task(
        id="assemble_task",
        type="reference.assemble",
        inputs=[
            TaskInput(name="title", value="A"),
            TaskInput(name="subtitle", value=None, get_from="upstream.subtitle"),
        ],
        params=[TaskParam(name="tag", value="demo")],
    )

    with pytest.raises(ToolBindingError, match="upstream.subtitle"):
        reference_actor.execute_task(task)


def test_assemble_missing_declared_output_raises_binding_error():
    """The other half of strict binding (issue-td-06): a tool under-returning its declared
    `TypedDict` output fails loudly rather than persisting the missing key as `None`.

    The actor must be constructed *inside* the patch, since `Actor.__init__` snapshots each
    tool method off the class at instantiation time (see `test_execute_task_survives_monkeypatched_tool_method`
    in `test_base_actor.py` for the same precedent).
    """
    task = Task(
        id="assemble_task",
        type="reference.assemble",
        inputs=[TaskInput(name="title", value="A"), TaskInput(name="subtitle", value="B")],
        params=[TaskParam(name="tag", value="demo")],
    )

    with patch.object(ReferenceActor, "assemble") as mock_assemble:
        mock_assemble.return_value = {}
        mock_assemble._tool_name = "assemble"

        actor = ReferenceActor()
        with pytest.raises(ToolBindingError, match="message"):
            actor.execute_task(task)


def test_passthrough_is_opaque_and_reads_task_inputs_directly(reference_actor):
    task = Task(
        id="passthrough_task",
        type="reference.passthrough",
        inputs=[TaskInput(name="message", value="hello"), TaskInput(name="anything_at_all", value=42)],
    )

    assert ReferenceActor.passthrough._descriptor.opaque is True
    result = reference_actor.execute_task(task)

    assert result == {"message": "hello", "anything_at_all": 42}


def test_wait_completes_without_cancellation(reference_actor):
    task = Task(id="wait_task", type="reference.wait", params=[TaskParam(name="seconds", value=0.02)])

    result = reference_actor.execute_task(task, context=ExecutionContext())

    assert result == {"cancelled": False}


def test_wait_stops_early_when_cancelled(reference_actor):
    task = Task(id="wait_task", type="reference.wait", params=[TaskParam(name="seconds", value=10)])
    context = ExecutionContext()
    context.cancel()

    result = reference_actor.execute_task(task, context=context)

    assert result == {"cancelled": True}
