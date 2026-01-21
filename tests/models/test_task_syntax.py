from antikythera.models import Task, DependencyType


def test_rshift_single():
    t1 = Task("1", "dummy")
    t2 = Task("2", "dummy")

    # t1 >> t2
    t1 >> t2

    assert len(t2.depends_on) == 1
    assert t2.depends_on[0].id == "1"


def test_rshift_list():
    t1 = Task("1", "dummy")
    t2 = Task("2", "dummy")
    t3 = Task("3", "dummy")

    # t1 >> [t2, t3]
    t1 >> [t2, t3]

    assert len(t2.depends_on) == 1
    assert t2.depends_on[0].id == "1"
    assert len(t3.depends_on) == 1
    assert t3.depends_on[0].id == "1"


def test_rrshift_list():
    t1 = Task("1", "dummy")
    t2 = Task("2", "dummy")
    t3 = Task("3", "dummy")

    # [t1, t2] >> t3
    [t1, t2] >> t3

    assert len(t3.depends_on) == 2
    ids = {d.id for d in t3.depends_on}
    assert ids == {"1", "2"}


def test_chaining():
    t1 = Task("1", "dummy")
    t2 = Task("2", "dummy")
    t3 = Task("3", "dummy")

    # t1 >> t2 >> t3
    t1 >> t2 >> t3

    assert len(t2.depends_on) == 1
    assert t2.depends_on[0].id == "1"
    assert len(t3.depends_on) == 1
    assert t3.depends_on[0].id == "2"


def test_fluid_graph():
    # t1 -> [t2, t3] -> t4
    t1 = Task("1", "dummy")
    t2 = Task("2", "dummy")
    t3 = Task("3", "dummy")
    t4 = Task("4", "dummy")

    t1 >> [t2, t3] >> t4

    assert len(t2.depends_on) == 1
    assert t2.depends_on[0].id == "1"
    assert len(t3.depends_on) == 1
    assert t3.depends_on[0].id == "1"

    assert len(t4.depends_on) == 2
    ids = {d.id for d in t4.depends_on}
    assert ids == {"2", "3"}


def test_dependency_type_preservation_with_then():
    # Note: >> operator defaults to FS (Finish-to-Start)
    # If users need specific types, they can still use .then() or mix them

    t1 = Task("1", "dummy")
    t2 = Task("2", "dummy")

    t1.then(t2, type=DependencyType.SS)

    assert len(t2.depends_on) == 1
    assert t2.depends_on[0].type == DependencyType.SS
