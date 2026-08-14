"""Deterministic, in-process simulation of a blueprint run.

The simulation drives the real :class:`TaskScheduler` over a real task graph and
nothing else: no broker, no storage, no agent launcher, no background thread. A run
therefore executes in milliseconds and shrinks cleanly, which is what makes properties
about whole runs affordable. See ADR-0006.

One iteration models one turn of the orchestrator's loop:

1. every task the scheduler reports as ready is dispatched, moving ``PENDING`` to
   ``READY`` and then to ``RUNNING`` — distinct states, because a Start-to-Start
   dependency is satisfied by ``RUNNING`` but not by ``READY``;
2. whichever running task ranks highest in the run's priority order reports its
   outcome, which is queued and processed exactly as an agent's message would be.

Completion order is an explicit input rather than an interactive draw, so one
blueprint can be run under two orders and the final states compared.

This is test infrastructure, not a production seam.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from dataclasses import field
from typing import Dict
from typing import List
from typing import Optional
from typing import Sequence
from typing import Tuple

from compas.datastructures import Graph

from antikythera.models import Blueprint
from antikythera.models import BlueprintSession
from antikythera.models import DependencyType
from antikythera.models import TaskCompletionMessage
from antikythera.models import TaskState
from antikythera_orchestrator.orchestrator import TaskScheduler
from antikythera_orchestrator.orchestrator import build_task_graph

TERMINAL_STATES = (TaskState.SUCCEEDED, TaskState.FAILED, TaskState.SKIPPED)


@dataclass(frozen=True)
class ObservedDependency:
    """The state of one dependency at the moment its dependent task was dispatched."""

    task_id: str
    type: DependencyType
    state: TaskState


@dataclass(frozen=True)
class Dispatch:
    """A task leaving ``PENDING``, with what its dependencies looked like at that moment."""

    task_id: str
    dependencies: Tuple[ObservedDependency, ...]


@dataclass
class RunResult:
    """The observable outcome of a simulated run.

    Attributes
    ----------
    final_states : dict[str, :class:`TaskState`]
        The state of every task, keyed by task ID, once the run settled.
    dispatches : list[:class:`Dispatch`]
        Every dispatch that happened, in order.
    messages : list[:class:`TaskCompletionMessage`]
        Every completion message fed to the scheduler, in order.
    settled : bool
        Whether the run reached a state with nothing ready and nothing running
        within its step budget. ``False`` means the run did not terminate.
    """

    final_states: Dict[str, TaskState] = field(default_factory=dict)
    dispatches: List[Dispatch] = field(default_factory=list)
    messages: List[TaskCompletionMessage] = field(default_factory=list)
    settled: bool = False
    _scheduler: Optional[TaskScheduler] = None
    _node_of: Dict[str, str] = field(default_factory=dict)

    def non_terminal_task_ids(self) -> List[str]:
        return sorted(task_id for task_id, state in self.final_states.items() if state not in TERMINAL_STATES)

    def states(self) -> Dict[str, TaskState]:
        """The state of every task right now, which after a late delivery may differ from ``final_states``."""
        return _states(self._scheduler.graph, self._node_of)

    def deliver(self, task_id: str, state: TaskState) -> None:
        """Feed one more completion through the scheduler, as a late message would arrive.

        The re-dispatch poller reports ``FAILED`` for a task it believes was never
        claimed, which can reach the scheduler after that task has actually
        succeeded.
        """
        self._scheduler.queue_message(TaskCompletionMessage(id=self._node_of[task_id], state=state))
        self._scheduler.process_queue()


def simulate_run(
    blueprint: Blueprint,
    priority: Sequence[str],
    outcomes: Optional[Dict[str, TaskState]] = None,
    duplicate_completions: bool = False,
    replay_completions: bool = False,
) -> RunResult:
    """Run *blueprint* through the scheduler until nothing more can happen.

    Parameters
    ----------
    blueprint : :class:`Blueprint`
        The blueprint to run. It is copied, so the caller's tasks keep their states
        and the same blueprint can be run more than once.
    priority : sequence[str]
        Task IDs, highest priority first. The running task ranked highest completes
        next.
    outcomes : dict[str, :class:`TaskState`], optional
        The terminal state each task reports. Defaults to ``SUCCEEDED``.
    duplicate_completions : bool, optional
        Queue every completion message twice, as the re-dispatch poller or a
        redelivering broker would.
    replay_completions : bool, optional
        Once the run has settled, feed every completion message through the
        scheduler a second time.

    Returns
    -------
    :class:`RunResult`
    """
    blueprint = deepcopy(blueprint)
    outcomes = outcomes or {}
    rank = {task_id: position for position, task_id in enumerate(priority)}

    graph = build_task_graph(blueprint)
    scheduler = TaskScheduler(BlueprintSession(bsid="simulated-session", blueprint=blueprint), graph)
    node_of = {graph.node[node]["task"].id: node for node in graph.nodes()}

    result = RunResult(_scheduler=scheduler, _node_of=node_of)

    # An iteration either completes a task or moves dispatched tasks into RUNNING, so
    # two iterations per task is a bound: a run needing more has not settled.
    for _ in range(2 * len(blueprint.tasks) + 4):
        dispatched = scheduler.get_pending_tasks()
        # Observe every dispatch before mutating any state, so what a property sees
        # is what the scheduler saw when it decided.
        for pending in dispatched:
            result.dispatches.append(_observe_dispatch(graph, node_of[pending.task.id]))

        # An agent claims a task only after the scheduler has had a chance to see it
        # sitting in READY. Advancing it in the same iteration it was dispatched would
        # make READY invisible, and with it the whole point of the state: a
        # Start-to-Start dependency is satisfied by RUNNING but not by READY.
        awaiting_claim = [task_id for task_id, node in node_of.items() if graph.node[node]["task"].state == TaskState.READY]

        for pending in dispatched:
            pending.task.state = TaskState.READY
        for task_id in awaiting_claim:
            graph.node[node_of[task_id]]["task"].state = TaskState.RUNNING

        running = [task_id for task_id, node in node_of.items() if graph.node[node]["task"].state == TaskState.RUNNING]

        if not running:
            if not dispatched:
                result.settled = True
                break
            # Everything just dispatched is still awaiting a claim; nothing to complete yet.
            continue

        completing = min(running, key=lambda task_id: rank[task_id])
        message = TaskCompletionMessage(id=node_of[completing], state=outcomes.get(completing, TaskState.SUCCEEDED))
        result.messages.append(message)

        scheduler.queue_message(message)
        if duplicate_completions:
            scheduler.queue_message(message)
        scheduler.process_queue()

    if replay_completions:
        for message in result.messages:
            scheduler.queue_message(message)
        scheduler.process_queue()

    result.final_states = _states(graph, node_of)
    return result


def _observe_dispatch(graph: Graph, node: str) -> Dispatch:
    dependencies = []
    for dependency_node in graph.neighbors_in(node):
        dependencies.append(
            ObservedDependency(
                task_id=graph.node[dependency_node]["task"].id,
                type=graph.edge_attribute((dependency_node, node), "type"),
                state=graph.node[dependency_node]["task"].state,
            )
        )
    return Dispatch(task_id=graph.node[node]["task"].id, dependencies=tuple(dependencies))


def _states(graph: Graph, node_of: Dict[str, str]) -> Dict[str, TaskState]:
    return {task_id: graph.node[node]["task"].state for task_id, node in node_of.items()}
