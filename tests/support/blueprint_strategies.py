"""Hypothesis strategies producing valid blueprints, and mutations that break them.

The generator's contract is exactly the set of blueprints :meth:`Blueprint.validate`
accepts: acyclic, exactly one ``START`` and one ``END``, no orphans, every dependency
resolvable, and ``END`` the only sink. Blueprints are built over a *fixed topological
order* with edges drawn only forward, so acyclicity holds by construction and no
generated example is ever discarded by a filter. See ADR-0006.

Because the generator is written to match ``validate()``, "everything generated is
valid" is a smoke test for the generator, not evidence about the validator. The
mutations below carry that weight: each takes a valid blueprint and breaks it in one
specific way, so a validator that accepted everything would fail them.

Generated tasks are skeletal — ``id``, ``type``, ``depends_on`` — because that is all
the scheduler and the graph builder read. Dependency types are ``FS`` and ``SS``, the
two the readiness check resolves; ``FF`` is deliberately excluded, since its failure
mode is a non-terminating run and that is the hardest thing to attribute when several
mechanisms are in play at once.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Dict
from typing import List
from typing import Set

from hypothesis import strategies as st

from antikythera.models import Blueprint
from antikythera.models import Dependency
from antikythera.models import DependencyType
from antikythera.models import SystemTaskType
from antikythera.models import Task
from antikythera.models import TaskState

#: The dependency types the scheduler's readiness check resolves.
SCHEDULABLE_DEPENDENCY_TYPES = [DependencyType.FS, DependencyType.SS]

#: Outcomes the scheduler treats identically across every dependency type.
SATISFYING_OUTCOMES = [TaskState.SUCCEEDED, TaskState.SKIPPED]

#: Outcomes including failure, which breaks the "every task ends terminal" claim.
ALL_OUTCOMES = SATISFYING_OUTCOMES + [TaskState.FAILED]

BLUEPRINT_ID = "generated_blueprint"
START_ID = "start"
END_ID = "end"
TASK_TYPE = "test.task"

MAX_INTERMEDIATE_TASKS = 8


@dataclass
class RunSpec:
    """Everything a simulated run is determined by.

    Attributes
    ----------
    blueprint : :class:`Blueprint`
        The blueprint to run.
    priority : list[str]
        A permutation of task IDs. The simulation always completes whichever
        running task ranks highest here, which is what makes a run reproducible
        and makes arrival-order independence expressible as two priorities over
        one blueprint.
    outcomes : dict[str, :class:`TaskState`]
        The terminal state each task reports when it completes.
    """

    blueprint: Blueprint
    priority: List[str]
    outcomes: Dict[str, TaskState]


@st.composite
def blueprints(draw, min_intermediate_tasks: int = 0, max_intermediate_tasks: int = MAX_INTERMEDIATE_TASKS) -> Blueprint:
    """Generate a valid blueprint of a handful to a dozen tasks.

    Topology variety rather than scale is what exercises the scheduler, so
    blueprints stay small but irregular: diamonds, fan-in, fan-out and
    skip-level dependencies all arise from drawing an arbitrary non-empty set
    of earlier tasks as each task's dependencies.
    """
    intermediate_count = draw(st.integers(min_value=min_intermediate_tasks, max_value=max_intermediate_tasks))
    ordered_ids = [START_ID] + [f"task_{i}" for i in range(intermediate_count)] + [END_ID]

    # Edges point forward in `ordered_ids`, so the result is acyclic by construction.
    parents: Dict[str, List[str]] = {}
    for position, task_id in enumerate(ordered_ids[1:-1], start=1):
        candidates = ordered_ids[:position]
        parents[task_id] = draw(st.lists(st.sampled_from(candidates), min_size=1, max_size=len(candidates), unique=True))

    end_parents: Set[str] = set(draw(st.lists(st.sampled_from(ordered_ids[:-1]), min_size=1, max_size=len(ordered_ids) - 1, unique=True)))
    # END must be the only sink: anything nothing else waits on is wired to END.
    with_successors = {parent for chosen in parents.values() for parent in chosen} | end_parents
    end_parents |= {task_id for task_id in ordered_ids[:-1] if task_id not in with_successors}
    parents[END_ID] = sorted(end_parents, key=ordered_ids.index)

    tasks = [Task(id=START_ID, type=SystemTaskType.START)]
    for task_id in ordered_ids[1:]:
        dependencies = [Dependency(id=parent, type=draw(st.sampled_from(SCHEDULABLE_DEPENDENCY_TYPES))) for parent in parents[task_id]]
        task_type = SystemTaskType.END if task_id == END_ID else TASK_TYPE
        tasks.append(Task(id=task_id, type=task_type, depends_on=dependencies))

    return Blueprint(id=BLUEPRINT_ID, name="Generated Blueprint", tasks=tasks)


@st.composite
def run_specs(draw, outcome_states=SATISFYING_OUTCOMES, **blueprint_kwargs) -> RunSpec:
    """Generate a blueprint together with a completion priority and per-task outcomes.

    ``START`` and ``END`` always succeed: skipping or failing them is an
    orchestrator-level concern rather than a scheduling one.
    """
    blueprint = draw(blueprints(**blueprint_kwargs))
    priority = draw(st.permutations([task.id for task in blueprint.tasks]))

    outcomes = {}
    for task in blueprint.tasks:
        if task.is_start or task.is_end:
            outcomes[task.id] = TaskState.SUCCEEDED
        else:
            outcomes[task.id] = draw(st.sampled_from(outcome_states))

    return RunSpec(blueprint=blueprint, priority=list(priority), outcomes=outcomes)


@dataclass
class Mutation:
    """A blueprint broken in one specific way.

    Attributes
    ----------
    tasks : list[:class:`Task`]
        The mutated tasks, ready to be handed to :class:`Blueprint`.
    culprits : list[str]
        The task IDs the rejection message is expected to name.
    """

    tasks: List[Task]
    culprits: List[str]


@st.composite
def blueprints_with_a_cycle(draw) -> Mutation:
    """Take a valid blueprint and add one backward edge, closing a cycle.

    The added dependency always points at a task reachable from the one
    receiving it, so the result is guaranteed cyclic rather than merely
    re-ordered.
    """
    blueprint = draw(blueprints(min_intermediate_tasks=1))
    tasks = deepcopy(blueprint.tasks)

    descendants = descendants_by_task(tasks)
    source = draw(st.sampled_from([task for task in tasks if descendants[task.id]]))
    target = draw(st.sampled_from(sorted(descendants[source.id])))

    source.depends_on.append(Dependency(id=target))

    return Mutation(tasks=tasks, culprits=[source.id, target])


@st.composite
def blueprints_with_a_detached_task(draw) -> Mutation:
    """Take a valid blueprint and detach one task so it can no longer reach ``END``.

    Every dependency on the victim is replaced by a dependency on the victim's
    own parents, so its successors keep at least one dependency and the
    blueprint stays acyclic. The victim becomes a second sink, and that is the
    only rule the result breaks.
    """
    blueprint = draw(blueprints(min_intermediate_tasks=1))
    tasks = deepcopy(blueprint.tasks)

    victim = draw(st.sampled_from([task for task in tasks if not (task.is_start or task.is_end)]))
    inherited = [dependency.id for dependency in victim.depends_on]

    for task in tasks:
        if not any(dependency.id == victim.id for dependency in task.depends_on):
            continue
        kept = [dependency for dependency in task.depends_on if dependency.id != victim.id]
        already = {dependency.id for dependency in kept}
        kept.extend(Dependency(id=parent) for parent in inherited if parent not in already)
        task.depends_on = kept

    return Mutation(tasks=tasks, culprits=[victim.id])


def unrecognised_dependency_types() -> st.SearchStrategy:
    """Strings that are not a :class:`DependencyType`, including plausible typos."""
    known = {member.value for member in DependencyType}
    plausible = st.sampled_from(["fs", "ss", "ff", "SF", "sf", "Start-to-Finish", "FSS", "", "FS "])
    return st.one_of(plausible, st.text(max_size=5)).filter(lambda value: value not in known)


def descendants_by_task(tasks: List[Task]) -> Dict[str, Set[str]]:
    """Map each task ID to the IDs of every task transitively depending on it."""
    return _transitive_closure({task.id: [dependency.id for dependency in task.depends_on] for task in tasks}, reverse=True)


def ancestors_by_task(tasks: List[Task]) -> Dict[str, Set[str]]:
    """Map each task ID to the IDs of every task it transitively depends on."""
    return _transitive_closure({task.id: [dependency.id for dependency in task.depends_on] for task in tasks}, reverse=False)


def _transitive_closure(parents: Dict[str, List[str]], reverse: bool) -> Dict[str, Set[str]]:
    adjacency: Dict[str, Set[str]] = {task_id: set() for task_id in parents}
    for task_id, task_parents in parents.items():
        for parent in task_parents:
            if reverse:
                adjacency[parent].add(task_id)
            else:
                adjacency[task_id].add(parent)

    closure: Dict[str, Set[str]] = {}
    for task_id in adjacency:
        reached: Set[str] = set()
        queue = list(adjacency[task_id])
        while queue:
            node = queue.pop()
            if node in reached:
                continue
            reached.add(node)
            queue.extend(adjacency[node])
        closure[task_id] = reached
    return closure
