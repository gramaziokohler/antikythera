from unittest.mock import patch

from antikythera.models import Task
from antikythera.models import TaskInput
from antikythera.models import TaskOutput
from antikythera.models import TaskParam
from antikythera_actors.user_interaction import UserInteractionActor


def test_user_input_user_output_and_notify_stay_opaque_and_document_why():
    """issue-td-11: all three keep `task: Task` because their shape is decided by the
    blueprint, not the tool — and each says so in its docstring.
    """
    assert UserInteractionActor.get_user_input._descriptor.opaque is True
    assert UserInteractionActor.show_user_output._descriptor.opaque is True
    assert UserInteractionActor.notify._descriptor.opaque is True

    assert "opaque" in (UserInteractionActor.get_user_input.__doc__ or "")
    assert "opaque" in (UserInteractionActor.show_user_output.__doc__ or "")
    assert "opaque" in (UserInteractionActor.notify.__doc__ or "")


def test_user_input_prompts_for_every_declared_output():
    task = Task(id="input_task", type="user_interaction.user_input", outputs=[TaskOutput(name="name"), TaskOutput(name="age")])

    with patch("builtins.input", side_effect=["Ada", "36"]):
        result = UserInteractionActor().execute_task(task)

    assert result == {"name": "Ada", "age": "36"}


def test_notify_still_resolves_title_and_message_from_either_input_or_param():
    """`notify`'s decision (issue-td-11) is to stay opaque precisely so this dual-source
    resolution keeps working unnarrowed for blueprints already relying on it.
    """
    task = Task(
        id="notify_task",
        type="user_interaction.notify",
        inputs=[TaskInput(name="message", value="Hello {name}")],
        params=[TaskParam(name="title", value="Greeting"), TaskParam(name="level", value="success")],
        context={"name": "World"},
    )

    result = UserInteractionActor().execute_task(task)

    assert result == {"status": "displayed"}
