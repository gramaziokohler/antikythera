from antikythera.models import Blueprint, Task, Dependency
from antikythera.models import SystemTaskType

def test_validate():
    # Valid blueprint
    t1 = Task(id="start", type=SystemTaskType.START)
    t2 = Task(id="task1", type="some.task", depends_on=[Dependency(id="start")])
    t3 = Task(id="end", type=SystemTaskType.END, depends_on=[Dependency(id="task1")])
    bp = Blueprint(id="bp1", name="Valid BP", tasks=[t1, t2, t3])
    bp.validate()
    print("Valid blueprint passed.")

    # Missing start
    bp_no_start = Blueprint(id="bp2", name="No Start", tasks=[t2, t3])
    try:
        bp_no_start.validate()
        print("Error: Missing start check failed.")
    except ValueError as e:
        print(f"Caught expected error (missing start): {e}")

    # Missing end
    bp_no_end = Blueprint(id="bp3", name="No End", tasks=[t1, t2])
    try:
        bp_no_end.validate()
        print("Error: Missing end check failed.")
    except ValueError as e:
        print(f"Caught expected error (missing end): {e}")

    # Orphan task
    t_orphan = Task(id="orphan", type="some.task") # No dependencies
    bp_orphan = Blueprint(id="bp4", name="Orphan", tasks=[t1, t2, t3, t_orphan])
    try:
        bp_orphan.validate()
        print("Error: Orphan task check failed.")
    except ValueError as e:
        print(f"Caught expected error (orphan): {e}")

    # Invalid dependency
    t_invalid_dep = Task(id="inv", type="some.task", depends_on=[Dependency(id="non_existent")])
    bp_invalid_dep = Blueprint(id="bp5", name="Invalid Dep", tasks=[t1, t2, t3, t_invalid_dep])
    try:
        bp_invalid_dep.validate()
        print("Error: Invalid dependency check failed.")
    except ValueError as e:
        print(f"Caught expected error (invalid dep): {e}")
