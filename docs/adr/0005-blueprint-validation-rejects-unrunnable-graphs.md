# ADR 0005: Blueprint validation rejects graphs the orchestrator cannot run

- Status: Accepted
- Date: 2026-08-14

## Context

`Blueprint.validate()` checked that a blueprint was well-formed: exactly one `START` task, exactly
one `END` task, no orphan tasks, and every dependency naming a task that exists. It did not check
that the resulting graph could actually be executed. Three gaps followed from that, each of which
fails silently rather than loudly:

1. **Cycles were accepted.** Two tasks depending on each other both satisfy the orphan and
   resolvable-dependency rules. The orchestrator builds the graph, and neither task ever becomes
   ready because each waits on the other. The session starts, runs `START`, and then stalls
   indefinitely with no error and no failed task.

2. **`END` was not required to be the only sink.** A task with no successors is not an orphan, so a
   blueprint could carry a side branch that nothing waits on. `Orchestrator._get_last_task` returns
   the *first* node it finds with out-degree zero, so which task is treated as "last" — and
   therefore when the session is marked `COMPLETED` — depended on graph iteration order rather than
   on the blueprint.

3. **Dependency types were never validated.** `Dependency.__init__` stored whatever it was given
   without coercion, so `"fs"`, `"SF"`, or any typo was retained as a plain string. The scheduler
   matches dependency types by equality, so an unrecognised type matched no branch, contributed no
   precondition, and left the task's precondition list empty — and an empty list is vacuously
   satisfied, dispatching the task immediately with its dependency ignored entirely.

The `SF` (Start-to-Finish) enum member was a specific instance of the third gap: it was declared in
`DependencyType` but implemented in neither `get_pending_tasks` nor `process_queue`.

## Decision

Validation's responsibility is to reject blueprints the orchestrator cannot run, not merely
blueprints that are malformed. Concretely:

1. `Blueprint.validate()` rejects cyclic dependency graphs.
2. `Blueprint.validate()` requires `END` to be the only sink — every task must have a path to `END`.
3. `Dependency.__init__` coerces `type` through `DependencyType`, raising on any unrecognised value.
4. `SF` is removed from `DependencyType`, so it is rejected by the same coercion as any other
   unimplemented type rather than being silently ignored.

Each rule is covered by a property test over generated blueprints, so the rules are executable
rather than merely documented.

## Consequences

- Blueprints that loaded before may now fail to load. No blueprint in `examples/` is affected: all
  18 are acyclic with `END` as their only sink, and all use `FS` exclusively.
- Failure moves from runtime to load time. A cyclic blueprint previously hung a session with no
  diagnostic; it now raises at construction, naming the cycle.
- Deliberate fire-and-forget side branches are no longer expressible. A task whose result nothing
  consumes must still connect to `END`. This is the cost of making session completion well-defined;
  if such branches are wanted later, `_get_last_task` needs to identify `END` by type rather than by
  out-degree, and that should be its own decision.
- `SF` becomes unavailable to blueprint authors. Nothing in the repository used it, and it is absent
  from the protobuf schema, so no wire compatibility is affected. Re-introducing it means
  implementing the finish-side constraint in `process_queue` alongside `FF`.

## Alternatives considered

**Leave validation as it is and document the gaps.** No blueprint stops loading, and the orchestrator
keeps whatever tolerance it has. Rejected because all three gaps fail silently — a hung session, a
session completing at the wrong moment, and a dependency ignored outright are each far harder to
diagnose at runtime than a load-time error is to fix.

**Reject cycles only.** A cycle is unambiguously never intentional, whereas a side branch might be.
Rejected because the multi-sink case is not merely untidy: it makes session completion depend on
iteration order, which is a correctness problem rather than a stylistic one.

**Remove `SF` from the enum without adding type coercion.** Rejected because it does not close the
hole. With no coercion, `"SF"` in a stored blueprint still deserialises to a plain string and is
still silently ignored; removing the enum member only relocates where that is visible. The same
silent-dispatch path is reachable by a lowercase typo, so coercion is the part that matters.
