"""Property-based tests for task graph construction.

``build_task_graph`` is the seam every scheduler property stands on, so what it
guarantees is worth stating directly: the scheduler reads a node's ``task`` and
``blueprint_id`` and an edge's ``type``, and looks nodes up by fully qualified ID.

Generated blueprints are flat, so the graph is built with no inner blueprints and an
empty composite mapping. Composite wiring is covered by the example-based
orchestrator tests.
"""

from hypothesis import given

from antikythera_orchestrator.orchestrator import build_task_graph
from tests.support.blueprint_strategies import blueprints


@given(blueprints())
def test_every_node_carries_its_task_and_blueprint_identity(blueprint):
    graph = build_task_graph(blueprint)

    assert set(graph.nodes()) == {f"{blueprint.id}.{task.id}" for task in blueprint.tasks}

    for task in blueprint.tasks:
        node = graph.node[f"{blueprint.id}.{task.id}"]
        assert node["task"] is task
        assert node["blueprint_id"] == blueprint.id


@given(blueprints())
def test_edge_count_equals_the_number_of_declared_dependencies(blueprint):
    graph = build_task_graph(blueprint)

    declared = sum(len(task.depends_on) for task in blueprint.tasks)

    assert graph.number_of_edges() == declared


@given(blueprints())
def test_every_edge_preserves_its_declared_dependency_type(blueprint):
    graph = build_task_graph(blueprint)

    for task in blueprint.tasks:
        for dependency in task.depends_on:
            edge = (f"{blueprint.id}.{dependency.id}", f"{blueprint.id}.{task.id}")
            assert graph.edge_attribute(edge, "type") == dependency.type
