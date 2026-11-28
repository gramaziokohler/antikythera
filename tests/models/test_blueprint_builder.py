"""Building blueprints in Python: `with Blueprint(...)` blocks, dict inputs and output links."""

import pytest

from antikythera.models import Blueprint
from antikythera.models import Dependency
from antikythera.models import OutputRef
from antikythera.models import Task
from antikythera.models import TaskInput


def _deps(task):
    return [d.id for d in task.depends_on]


def test_tasks_created_in_the_block_join_the_blueprint():
    with Blueprint("bp") as blueprint:
        Task("a", "x.a")
        Task("b", "x.b")

    assert [t.id for t in blueprint.tasks] == ["start", "a", "b", "end"]
    assert blueprint.name == "bp"


def test_start_and_end_are_wired_to_loose_tasks():
    with Blueprint("bp") as blueprint:
        a = Task("a", "x.a")
        b = Task("b", "x.b")
        c = Task("c", "x.c")
        a >> b

    assert _deps(a) == ["start"]
    assert _deps(b) == ["a"]
    assert _deps(c) == ["start"]
    assert _deps(blueprint.end) == ["b", "c"]


def test_explicit_start_and_end_are_kept():
    with Blueprint("bp") as blueprint:
        a = Task("a", "x.a")
        b = Task("b", "x.b")
        blueprint.start >> a >> blueprint.end
        a >> b

    assert _deps(a) == ["start"]
    assert _deps(blueprint.end) == ["a", "b"]
    assert len([t for t in blueprint.tasks if t.is_end]) == 1


def test_own_start_task_is_used():
    with Blueprint("bp") as blueprint:
        begin = Task("begin", "system.start")
        a = Task("a", "x.a")

    assert blueprint.start is begin
    assert _deps(a) == ["begin"]


def test_empty_block_connects_start_to_end():
    with Blueprint("bp") as blueprint:
        pass

    assert _deps(blueprint.end) == ["start"]


def test_nested_blocks_keep_their_tasks():
    with Blueprint("outer") as outer:
        Task("a", "x.a")
        with Blueprint("inner") as inner:
            Task("b", "x.b")
        Task("c", "x.c")

    assert [t.id for t in outer.tasks] == ["start", "a", "c", "end"]
    assert [t.id for t in inner.tasks] == ["start", "b", "end"]


def test_tasks_outside_a_block_join_nothing():
    with Blueprint("bp") as blueprint:
        pass
    Task("late", "x.late")

    assert "late" not in [t.id for t in blueprint.tasks]


def test_block_with_an_error_is_not_validated():
    with pytest.raises(RuntimeError, match="boom"):
        with Blueprint("bp"):
            Task("a", "x.a", depends_on=["missing"])
            raise RuntimeError("boom")


def test_block_validates_on_exit():
    with pytest.raises(ValueError, match="non-existent"):
        with Blueprint("bp"):
            Task("a", "x.a", depends_on=["missing"])


def test_blueprint_with_tasks_is_unchanged():
    start, end = Task("start", "system.start"), Task("end", "system.end")
    start >> end
    blueprint = Blueprint(id="bp", name="Name", tasks=[start, end])

    assert blueprint.name == "Name"
    assert blueprint.start is start


def test_dict_inputs_params_and_output_names():
    task = Task("t", "x.t", inputs={"name": "world"}, params={"duration": 5}, outputs=["greeting"])

    assert (task.inputs[0].name, task.inputs[0].value, task.inputs[0].get_from) == ("name", "world", None)
    assert task.get_param_value("duration") == 5
    assert task.outputs[0].name == "greeting"


def test_depends_on_accepts_tasks_and_ids():
    a = Task("a", "x.a")
    b = Task("b", "x.b", depends_on=[a, "start", Dependency("other")])

    assert _deps(b) == ["a", "start", "other"]


def test_output_link_reads_the_output_and_depends_on_its_task():
    cut = Task("cut", "press.cut")
    link = cut.output("sheet")
    stamp = Task("stamp", "stamper.stamp", inputs={"sheet": link})

    assert isinstance(link, OutputRef)
    assert link == "cut.sheet" and link.task_id == "cut" and link.name == "sheet"
    assert cut.get_output("sheet").set_to == "cut.sheet"
    assert stamp.inputs[0].get_from == "cut.sheet"
    assert type(stamp.inputs[0].get_from) is str
    assert _deps(stamp) == ["cut"]


def test_output_link_keeps_an_explicit_set_to():
    cut = Task("cut", "press.cut", outputs=["sheet"])
    cut.get_output("sheet").set_to = "latest_sheet"

    assert cut.output("sheet") == "latest_sheet"


def test_output_link_in_a_task_input_adds_the_dependency_once():
    cut = Task("cut", "press.cut")
    stamp = Task("stamp", "stamper.stamp", inputs=[TaskInput(name="sheet", get_from=cut.output("sheet"))], depends_on=[cut])

    assert _deps(stamp) == ["cut"]


def test_rshift_does_not_duplicate_dependencies():
    a, b = Task("a", "x.a"), Task("b", "x.b")
    a >> b
    a >> b
    [a] >> b

    assert _deps(b) == ["a"]


def test_built_blueprint_round_trips_through_json():
    with Blueprint("bp") as blueprint:
        cut = Task("cut", "press.cut", inputs={"number": 1})
        Task("stamp", "stamper.stamp", inputs={"sheet": cut.output("sheet")})

    loaded = Blueprint.from_jsonstring(blueprint.to_jsonstring())

    assert [t.id for t in loaded.tasks] == ["start", "cut", "stamp", "end"]
    assert loaded.tasks[2].inputs[0].get_from == "cut.sheet"
    assert loaded.tasks[1].outputs[0].set_to == "cut.sheet"
