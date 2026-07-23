import pytest

from antikythera.models import Blueprint
from antikythera.models import Dependency
from antikythera.models import SystemTaskType
from antikythera.models import Task
from antikythera.models import TaskOutput
from antikythera.models import TaskParam


def test_validate_valid_blueprint():
    t1 = Task(id="start", type=SystemTaskType.START)
    t2 = Task(id="task1", type="some.task", depends_on=[Dependency(id="start")])
    t3 = Task(id="end", type=SystemTaskType.END, depends_on=[Dependency(id="task1")])
    bp = Blueprint(id="bp1", name="Valid BP", tasks=[t1, t2, t3])
    # Should not raise
    bp.validate()


def test_validate_missing_start():
    t1 = Task(id="task1", type="some.task", depends_on=[])
    t2 = Task(id="end", type=SystemTaskType.END, depends_on=[Dependency(id="task1")])

    with pytest.raises(ValueError, match="must have exactly one start task"):
        Blueprint(id="bp2", name="No Start", tasks=[t1, t2])


def test_validate_multiple_starts():
    t1 = Task(id="start1", type=SystemTaskType.START)
    t2 = Task(id="start2", type=SystemTaskType.START)
    t3 = Task(id="end", type=SystemTaskType.END, depends_on=[Dependency(id="start1"), Dependency(id="start2")])

    with pytest.raises(ValueError, match="must have exactly one start task"):
        Blueprint(id="bp_multi_start", name="Multi Start", tasks=[t1, t2, t3])


def test_validate_missing_end():
    t1 = Task(id="start", type=SystemTaskType.START)
    t2 = Task(id="task1", type="some.task", depends_on=[Dependency(id="start")])

    with pytest.raises(ValueError, match="must have exactly one end task"):
        Blueprint(id="bp3", name="No End", tasks=[t1, t2])


def test_validate_multiple_ends():
    t1 = Task(id="start", type=SystemTaskType.START)
    t2 = Task(id="end1", type=SystemTaskType.END, depends_on=[Dependency(id="start")])
    t3 = Task(id="end2", type=SystemTaskType.END, depends_on=[Dependency(id="start")])

    with pytest.raises(ValueError, match="must have exactly one end task"):
        Blueprint(id="bp_multi_end", name="Multi End", tasks=[t1, t2, t3])


def test_validate_orphan_task():
    t1 = Task(id="start", type=SystemTaskType.START)
    t2 = Task(id="task1", type="some.task", depends_on=[Dependency(id="start")])
    t3 = Task(id="end", type=SystemTaskType.END, depends_on=[Dependency(id="task1")])
    t_orphan = Task(id="orphan", type="some.task")  # No dependencies

    with pytest.raises(ValueError, match="is an orphan"):
        Blueprint(id="bp4", name="Orphan", tasks=[t1, t2, t3, t_orphan])


def test_validate_invalid_dependency():
    t1 = Task(id="start", type=SystemTaskType.START)
    t2 = Task(id="task1", type="some.task", depends_on=[Dependency(id="start")])
    t3 = Task(id="end", type=SystemTaskType.END, depends_on=[Dependency(id="task1")])
    t_invalid = Task(id="inv", type="some.task", depends_on=[Dependency(id="non_existent")])

    with pytest.raises(ValueError, match="depends on non-existent task"):
        Blueprint(id="bp5", name="Invalid Dep", tasks=[t1, t2, t3, t_invalid])


def _scope_blueprint(while_condition=None, body_outputs=None, body_params=None, body_condition=None):
    """start -> scope_open -> body -> scope_close -> end, with configurable conditions."""
    scope_start = {"while_policy": {"condition": while_condition}} if while_condition else {}
    return Blueprint(
        id="bp_scope",
        name="Scope BP",
        tasks=[
            Task(id="start", type=SystemTaskType.START),
            Task(id="scope_open", type="some.task", scope_start=scope_start, depends_on=[Dependency(id="start")]),
            Task(
                id="body",
                type="some.task",
                condition=body_condition,
                outputs=body_outputs or [],
                params=body_params or [],
                depends_on=[Dependency(id="scope_open")],
            ),
            Task(id="scope_close", type="some.task", scope_end="scope_open", depends_on=[Dependency(id="body")]),
            Task(id="end", type=SystemTaskType.END, depends_on=[Dependency(id="scope_close")]),
        ],
    )


def test_check_dataflow_flags_unproduced_while_condition_name():
    bp = _scope_blueprint(while_condition="elements_remaining > 0")

    warnings = bp.check_dataflow()

    assert len(warnings) == 1
    assert "elements_remaining" in warnings[0]
    assert "scope_open" in warnings[0]


def test_check_dataflow_does_not_raise_from_validate():
    bp = _scope_blueprint(while_condition="elements_remaining > 0")
    # An unresolved name is a warning, not a validation error: agents may write
    # outputs the blueprint never declares.
    bp.validate()


def test_check_dataflow_accepts_name_produced_by_task_output():
    bp = _scope_blueprint(while_condition="counter < 3", body_outputs=[TaskOutput(name="counter")])

    assert bp.check_dataflow() == []


def test_check_dataflow_accepts_name_produced_via_set_to():
    bp = _scope_blueprint(while_condition="elements_remaining > 0", body_outputs=[TaskOutput(name="remaining", set_to="elements_remaining")])

    assert bp.check_dataflow() == []


def test_check_dataflow_ignores_builtins_and_bound_names():
    bp = _scope_blueprint(while_condition="len([x for x in items if x]) > 0", body_outputs=[TaskOutput(name="items")])

    assert bp.check_dataflow() == []


def test_check_dataflow_flags_unparsable_condition():
    bp = _scope_blueprint(while_condition="counter >")

    warnings = bp.check_dataflow()

    assert len(warnings) == 1
    assert "not a valid expression" in warnings[0]


def test_check_dataflow_accepts_skip_condition_reading_own_param():
    # Skip conditions are evaluated with the task's own params in scope.
    bp = _scope_blueprint(body_condition="threshold > 1", body_params=[TaskParam(name="threshold", value=2)])

    assert bp.check_dataflow() == []


def test_check_dataflow_flags_unproduced_skip_condition_name():
    bp = _scope_blueprint(body_condition="needs_processing")

    warnings = bp.check_dataflow()

    assert len(warnings) == 1
    assert "needs_processing" in warnings[0]
