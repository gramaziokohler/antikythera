"""Property-based tests for the task scheduler.

Each property runs a generated blueprint through the real :class:`TaskScheduler` over
a real task graph, driven by :func:`simulate_run`. Nothing below the transport is
involved — no broker, no storage, no agent launcher, no background thread — and no
property inspects the scheduler's internals: a run is observed only through the states
its tasks end in and the moments at which tasks were dispatched.

The per-example deadline is disabled throughout: a wall-clock limit per example turns
a slow CI runner into a spurious failure, and it protects against nothing here, since
a run that fails to terminate is caught by the simulation's step budget instead.
"""

from hypothesis import given
from hypothesis import settings
from hypothesis import strategies as st

from antikythera.models import DependencyType
from antikythera.models import TaskState
from tests.support.blueprint_strategies import ALL_OUTCOMES
from tests.support.blueprint_strategies import ancestors_by_task
from tests.support.blueprint_strategies import run_specs
from tests.support.simulation import TERMINAL_STATES
from tests.support.simulation import simulate_run


def assert_every_dispatch_was_permitted(result):
    """No task starts before its dependencies allow it.

    This is the scheduler's core safety guarantee: a Finish-to-Start dependency must
    have reached a satisfying terminal state, and a Start-to-Start dependency must at
    least have started running.
    """
    for dispatch in result.dispatches:
        for dependency in dispatch.dependencies:
            if dependency.type == DependencyType.FS:
                assert dependency.state in (TaskState.SUCCEEDED, TaskState.SKIPPED), (
                    f"{dispatch.task_id} dispatched while FS dependency {dependency.task_id} was {dependency.state}"
                )
            elif dependency.type == DependencyType.SS:
                assert dependency.state in (
                    TaskState.RUNNING,
                    TaskState.SUCCEEDED,
                    TaskState.SKIPPED,
                ), f"{dispatch.task_id} dispatched while SS dependency {dependency.task_id} was {dependency.state}"


@settings(deadline=None)
@given(run_specs())
def test_no_task_is_dispatched_before_its_dependencies_permit_it(spec):
    assert_every_dispatch_was_permitted(simulate_run(spec.blueprint, spec.priority, spec.outcomes))


@settings(deadline=None)
@given(run_specs())
def test_a_run_reaches_a_state_where_every_task_is_terminal(spec):
    """With satisfying outcomes only, nothing can stall: the run always finishes.

    ``SUCCEEDED`` and ``SKIPPED`` are treated identically by the scheduler across
    every dependency type, so the strong claim holds. Failure gets its own,
    deliberately weaker property below.
    """
    result = simulate_run(spec.blueprint, spec.priority, spec.outcomes)

    assert result.settled, "run did not settle within its step budget"
    assert result.non_terminal_task_ids() == []
    assert set(result.final_states) == {task.id for task in spec.blueprint.tasks}


@settings(deadline=None)
@given(run_specs())
def test_every_task_is_dispatched_exactly_once(spec):
    result = simulate_run(spec.blueprint, spec.priority, spec.outcomes)

    dispatched = [dispatch.task_id for dispatch in result.dispatches]

    assert sorted(dispatched) == sorted(task.id for task in spec.blueprint.tasks)


@settings(deadline=None)
@given(run_specs(), st.data())
def test_completion_order_does_not_change_the_final_state(spec, data):
    other_priority = data.draw(st.permutations([task.id for task in spec.blueprint.tasks]))

    one = simulate_run(spec.blueprint, spec.priority, spec.outcomes)
    another = simulate_run(spec.blueprint, other_priority, spec.outcomes)

    assert one.final_states == another.final_states


@settings(deadline=None)
@given(run_specs())
def test_duplicate_completions_do_not_change_the_final_state(spec):
    once = simulate_run(spec.blueprint, spec.priority, spec.outcomes)
    twice = simulate_run(spec.blueprint, spec.priority, spec.outcomes, duplicate_completions=True)

    assert twice.final_states == once.final_states


@settings(deadline=None)
@given(run_specs(outcome_states=ALL_OUTCOMES))
def test_replaying_completions_leaves_the_final_state_unchanged(spec):
    plain = simulate_run(spec.blueprint, spec.priority, spec.outcomes)
    replayed = simulate_run(spec.blueprint, spec.priority, spec.outcomes, replay_completions=True)

    assert replayed.final_states == plain.final_states


@settings(deadline=None)
@given(run_specs(outcome_states=ALL_OUTCOMES), st.sampled_from(ALL_OUTCOMES))
def test_a_late_completion_cannot_change_a_task_that_already_finished(spec, late_state):
    """The re-dispatch poller reports ``FAILED`` for a task it believes was never claimed.

    That report can reach the scheduler after the task has actually succeeded, so
    a completion for a task already in a terminal state must change nothing —
    whatever state it carries. This is the guard the poller depends on to not
    corrupt the run it was meant to protect.
    """
    result = simulate_run(spec.blueprint, spec.priority, spec.outcomes)
    settled_states = dict(result.final_states)

    for task_id, state in settled_states.items():
        if state in TERMINAL_STATES:
            result.deliver(task_id, late_state)

    assert result.states() == settled_states


@settings(deadline=None)
@given(run_specs(outcome_states=ALL_OUTCOMES))
def test_every_non_terminal_task_has_a_failed_ancestor(spec):
    """With failures admitted, "the run stopped" must always be attributable.

    A task left non-terminal is only acceptable if something it depends on, however
    far upstream, failed. Anything else is a scheduling defect.
    """
    result = simulate_run(spec.blueprint, spec.priority, spec.outcomes)

    assert result.settled, "run did not settle within its step budget"
    assert_every_dispatch_was_permitted(result)

    ancestors = ancestors_by_task(spec.blueprint.tasks)
    failed = {task_id for task_id, state in result.final_states.items() if state == TaskState.FAILED}

    for task_id in result.non_terminal_task_ids():
        assert ancestors[task_id] & failed, f"{task_id} is not terminal but no task it depends on failed"
