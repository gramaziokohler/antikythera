import pytest
from antikythera.models import Blueprint, Task, Dependency, SystemTaskType


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
    bp = Blueprint(id="bp2", name="No Start", tasks=[t1, t2])

    with pytest.raises(ValueError, match="must have exactly one start task"):
        bp.validate()


def test_validate_multiple_starts():
    t1 = Task(id="start1", type=SystemTaskType.START)
    t2 = Task(id="start2", type=SystemTaskType.START)
    t3 = Task(id="end", type=SystemTaskType.END, depends_on=[Dependency(id="start1"), Dependency(id="start2")])
    bp = Blueprint(id="bp_multi_start", name="Multi Start", tasks=[t1, t2, t3])

    with pytest.raises(ValueError, match="must have exactly one start task"):
        bp.validate()


def test_validate_missing_end():
    t1 = Task(id="start", type=SystemTaskType.START)
    t2 = Task(id="task1", type="some.task", depends_on=[Dependency(id="start")])
    bp = Blueprint(id="bp3", name="No End", tasks=[t1, t2])

    with pytest.raises(ValueError, match="must have exactly one end task"):
        bp.validate()


def test_validate_multiple_ends():
    t1 = Task(id="start", type=SystemTaskType.START)
    t2 = Task(id="end1", type=SystemTaskType.END, depends_on=[Dependency(id="start")])
    t3 = Task(id="end2", type=SystemTaskType.END, depends_on=[Dependency(id="start")])
    bp = Blueprint(id="bp_multi_end", name="Multi End", tasks=[t1, t2, t3])

    with pytest.raises(ValueError, match="must have exactly one end task"):
        bp.validate()


def test_validate_orphan_task():
    t1 = Task(id="start", type=SystemTaskType.START)
    t2 = Task(id="task1", type="some.task", depends_on=[Dependency(id="start")])
    t3 = Task(id="end", type=SystemTaskType.END, depends_on=[Dependency(id="task1")])
    t_orphan = Task(id="orphan", type="some.task")  # No dependencies

    bp = Blueprint(id="bp4", name="Orphan", tasks=[t1, t2, t3, t_orphan])

    with pytest.raises(ValueError, match="is an orphan"):
        bp.validate()


def test_validate_invalid_dependency():
    t1 = Task(id="start", type=SystemTaskType.START)
    t2 = Task(id="task1", type="some.task", depends_on=[Dependency(id="start")])
    t3 = Task(id="end", type=SystemTaskType.END, depends_on=[Dependency(id="task1")])
    t_invalid = Task(id="inv", type="some.task", depends_on=[Dependency(id="non_existent")])

    bp = Blueprint(id="bp5", name="Invalid Dep", tasks=[t1, t2, t3, t_invalid])

    with pytest.raises(ValueError, match="depends on non-existent task"):
        bp.validate()
