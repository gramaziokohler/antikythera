"""Property-based tests for blueprint validation.

Every property here is expressed at the same public seam as the example-based tests
next door: a blueprint is constructed and either raises or does not.

Note that ``test_generated_blueprints_are_accepted`` is a smoke test for the
*generator*, not evidence about the validator — the generator is written to match
``validate()``, so a validator that accepted everything would pass it. The mutation
properties below carry the real weight: each takes a valid blueprint and breaks it in
one specific way.
"""

import json

import pytest
from compas.data import json_dumps
from compas.data import json_loads
from hypothesis import given
from hypothesis import settings
from hypothesis import strategies as st

from antikythera.io import BlueprintJsonSerializer
from antikythera.models import Blueprint
from antikythera.models import Dependency
from antikythera.models import DependencyType
from tests.support.blueprint_strategies import blueprints
from tests.support.blueprint_strategies import blueprints_with_a_cycle
from tests.support.blueprint_strategies import blueprints_with_a_detached_task
from tests.support.blueprint_strategies import unrecognised_dependency_types


@given(blueprints())
def test_generated_blueprints_are_accepted(blueprint):
    blueprint.validate()


@given(blueprints_with_a_cycle())
def test_blueprint_with_a_cycle_is_rejected(mutation):
    with pytest.raises(ValueError, match="dependency cycle") as raised:
        Blueprint(id="mutated", name="Mutated", tasks=mutation.tasks)

    for task_id in mutation.culprits:
        assert task_id in str(raised.value)


@given(blueprints_with_a_detached_task())
def test_blueprint_with_a_task_that_cannot_reach_end_is_rejected(mutation):
    with pytest.raises(ValueError, match="cannot reach the end task") as raised:
        Blueprint(id="mutated", name="Mutated", tasks=mutation.tasks)

    for task_id in mutation.culprits:
        assert task_id in str(raised.value)


@given(unrecognised_dependency_types())
def test_unrecognised_dependency_type_is_rejected_at_construction(value):
    with pytest.raises(ValueError):
        Dependency(id="some_task", type=value)


@given(st.sampled_from(list(DependencyType)))
def test_recognised_dependency_type_survives_construction(value):
    assert Dependency(id="some_task", type=value).type is DependencyType(value)
    assert Dependency(id="some_task", type=value.value).type is DependencyType(value)


# The deadline is disabled on the two serialization properties because the first
# example pays for compas' one-time serializer registration, which is enough on its
# own to exceed a per-example wall-clock limit.
@settings(deadline=None)
@given(blueprints(min_intermediate_tasks=1), st.data())
def test_blueprint_json_with_a_corrupted_dependency_type_fails_to_load(blueprint, data):
    """A corrupted type must be rejected on the way in, not stored verbatim."""
    serialized = BlueprintJsonSerializer.serialize(blueprint)
    _corrupt_one_dependency_type(serialized["tasks"], data)

    with pytest.raises(ValueError):
        BlueprintJsonSerializer.BlueprintSerializer.from_dict(serialized)


@settings(deadline=None)
@given(blueprints(min_intermediate_tasks=1), st.data())
def test_stored_blueprint_with_a_corrupted_dependency_type_fails_to_load(blueprint, data):
    """The same holds for the compas data round-trip used for stored sessions."""
    serialized = json.loads(json_dumps(blueprint))
    _corrupt_one_dependency_type([task["data"] for task in serialized["data"]["tasks"]], data, unwrap=True)

    with pytest.raises(ValueError):
        json_loads(json.dumps(serialized))


def _corrupt_one_dependency_type(tasks, data, unwrap=False):
    task = data.draw(st.sampled_from([task for task in tasks if task.get("depends_on")]))
    dependency = data.draw(st.sampled_from(task["depends_on"]))
    if unwrap:
        dependency = dependency["data"]
    dependency["type"] = data.draw(unrecognised_dependency_types())
