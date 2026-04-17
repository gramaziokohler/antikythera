"""Scope policies for controlling looping/retry behavior within a blueprint.

A Scope is a contiguous region of a blueprint DAG delimited by a
``scope_start`` task and a ``scope_end`` task.  After the scope_end task
completes, the Scope's policy decides whether all scope tasks should be
reset and re-executed (loop) or if execution should continue forward.

Three policies are supported (a fourth — compensating scope — is future work):

* **skip** – No explicit policy definition needed.  A ``condition`` on the
  scope_start task is evaluated; if it returns False the entire scope is
  skipped.
* **retry** – Re-runs the scope a fixed number of times.
* **while** – Re-runs the scope as long as a condition expression evaluates
  to True in the current session data (with an optional iteration cap).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Dict
from typing import Optional

from compas.datastructures import Graph

from antikythera.models import BlueprintSession
from antikythera.models import Task
from antikythera.models import TaskState

from .conditionals import safe_eval_condition

LOG = logging.getLogger(__name__)


@dataclass
class RuntimeScope:
    """Runtime representation of a scope within the flattened execution graph.

    Built from the model-level :class:`~antikythera.models.Scope` stored on
    each :class:`~antikythera.models.Blueprint`, augmented with
    fully-qualified node IDs from the execution graph.

    Attributes
    ----------
    name : str
        Identifier for this scope — the task ID of the ``scope_start`` task.
    start_fqn : str
        Fully-qualified node ID of the scope_start task.
    end_fqn : str
        Fully-qualified node ID of the scope_end task.
    task_fqns : set[str]
        All fully-qualified node IDs that belong to this scope (including
        start and end).
    policy : dict
        Raw policy dict from ``task.scope_start`` (contains ``retry_policy``
        and/or ``while_policy``).
    """

    name: str
    start_fqn: str
    end_fqn: str
    task_fqns: set = field(default_factory=set)
    policy: dict = field(default_factory=dict)

    # -- Policy introspection ------------------------------------------------

    @property
    def retry_policy(self) -> Optional[dict]:
        return self.policy.get("retry_policy")

    @property
    def while_policy(self) -> Optional[dict]:
        return self.policy.get("while_policy")

    # -- Loop evaluation -----------------------------------------------------

    def should_loop(self, iterations_so_far: int, eval_context: Dict[str, Any]) -> bool:
        """Decide whether the scope should reset for another iteration.

        Parameters
        ----------
        iterations_so_far : int
            Number of *extra* iterations already completed (0 after the first
            run through the scope).
        eval_context : dict
            Session data + blueprint context used to evaluate while-conditions.

        Returns
        -------
        bool
        """
        if self.retry_policy:
            return self._evaluate_retry(iterations_so_far)
        if self.while_policy:
            return self._evaluate_while(iterations_so_far, eval_context)
        return False

    def _evaluate_retry(self, iterations_so_far: int) -> bool:
        max_retries = self.retry_policy.get("retries", 0)
        if iterations_so_far < max_retries:
            LOG.info(f"Scope '{self.name}': retry {iterations_so_far + 1}/{max_retries}")
            return True
        LOG.info(f"Scope '{self.name}': all {max_retries} retries exhausted, continuing.")
        return False

    def _evaluate_while(self, iterations_so_far: int, eval_context: Dict[str, Any]) -> bool:
        max_iterations = self.while_policy.get("max_iterations")
        condition = self.while_policy.get("condition")

        if max_iterations is not None and iterations_so_far >= max_iterations - 1:
            LOG.info(f"Scope '{self.name}': max_iterations ({max_iterations}) reached, stopping.")
            return False

        if not condition:
            return False

        try:
            result = safe_eval_condition(condition, eval_context)
            LOG.info(f"Scope '{self.name}': while condition '{condition}' evaluated to {result}.")
            return result
        except Exception as e:
            LOG.error(f"Error evaluating while condition for scope '{self.name}': {e}")
            return False

    # -- Task reset ----------------------------------------------------------

    def reset_tasks(self, graph: Graph) -> None:
        """Reset all tasks in this scope back to PENDING and clear their outputs."""
        for fqn_task_id in self.task_fqns:
            node_data = graph.node.get(fqn_task_id)
            if not node_data:
                continue
            task: Task = node_data["task"]
            task.state = TaskState.PENDING
            for output in task.outputs:
                output.value = None

    def skip_tasks(self, graph: Graph, excluded_fqn: str) -> None:
        """Mark all scope tasks (except *excluded_fqn*) as SKIPPED."""
        for fqn_task_id in self.task_fqns:
            if fqn_task_id == excluded_fqn:
                continue
            node_data = graph.node.get(fqn_task_id)
            if not node_data:
                continue
            task: Task = node_data["task"]
            if task.state == TaskState.PENDING:
                task.state = TaskState.SKIPPED
                LOG.debug(f"Cascaded SKIP to scope task '{fqn_task_id}' (scope '{self.name}').")


class ScopeRegistry:
    """Discovers and manages all runtime scopes from blueprint scope definitions."""

    def __init__(self, session: BlueprintSession, graph: Graph) -> None:
        self._scopes: Dict[str, RuntimeScope] = {}
        self._build(session, graph)

    def __contains__(self, scope_name: str) -> bool:
        return scope_name in self._scopes

    def get(self, scope_name: str) -> Optional[RuntimeScope]:
        return self._scopes.get(scope_name)

    # -- Construction --------------------------------------------------------

    def _build(self, session: BlueprintSession, graph: Graph) -> None:
        all_blueprints = [session.blueprint] + list(session.inner_blueprints.values())

        for blueprint in all_blueprints:
            for model_scope in blueprint.scopes:
                start_fqn = f"{blueprint.id}.{model_scope.id}"
                end_fqn = f"{blueprint.id}.{model_scope.end_task_id}"

                scope = RuntimeScope(
                    name=model_scope.id,
                    start_fqn=start_fqn,
                    end_fqn=end_fqn,
                    task_fqns=_find_scope_tasks(graph, start_fqn, end_fqn),
                    policy=model_scope.policy,
                )
                self._scopes[model_scope.id] = scope
                LOG.debug(f"Registered scope '{model_scope.id}' with {len(scope.task_fqns)} tasks: {start_fqn} -> {end_fqn}")


def _find_scope_tasks(graph: Graph, start_fqn: str, end_fqn: str) -> set:
    """Return FQN task IDs between (and including) scope_start and scope_end.

    Computed as the intersection of nodes reachable forward from *start_fqn*
    and nodes reachable backward from *end_fqn*.
    """
    return _reachable(graph, start_fqn, forward=True) & _reachable(graph, end_fqn, forward=False)


def _reachable(graph: Graph, origin: str, *, forward: bool) -> set:
    visited: set = set()
    queue = [origin]
    neighbors_fn = graph.neighbors_out if forward else graph.neighbors_in
    while queue:
        node = queue.pop()
        if node in visited:
            continue
        visited.add(node)
        queue.extend(neighbors_fn(node))
    return visited
