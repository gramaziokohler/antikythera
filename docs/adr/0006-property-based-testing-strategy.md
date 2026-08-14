# ADR 0006: Property-based testing targets the scheduler through generated blueprints

- Status: Accepted
- Date: 2026-08-14

## Context

The orchestrator's correctness rests on properties that are awkward to express as examples. Task
completion messages arrive over MQTT with no ordering guarantee, the scheduler drains them from a
LIFO queue, the re-dispatch poller can inject duplicate completions, and dependencies come in
several kinds with different satisfaction rules. Example-based tests pin down individual scenarios
but say nothing about the space around them, and the interesting failures — a run that stalls, a
session that completes at the wrong moment, a state that depends on arrival order — live in that
space.

The existing orchestrator tests run against a live `AgentLauncher` over an in-memory transport and
wait on `await_completion(timeout=...)`. That shape cannot carry property tests: hypothesis runs
each property many times and shrinks by re-running, so wall-clock waits make the suite slow and
shrinking useless against nondeterminism.

`TaskScheduler` turns out to be far more testable than its surroundings suggest. It is constructed
with a session and a graph but reads only the graph — readiness, queue processing and dependency
resolution are all pure functions of graph state. The obstacle is not the scheduler but the graph:
the only code that builds one is a method on `Orchestrator`, whose constructor opens an MQTT
transport, subscribes to five topics, connects to storage twice and starts a poller thread.

## Decision

Property tests target two tiers, sharing one generator, and stay entirely below the transport.

**Generator.** Blueprints are built over a fixed topological order with edges drawn only forward, so
acyclicity holds by construction and no example is ever filtered away. Tasks are skeletal — `id`,
`type`, `depends_on` — because that is all the scheduler and the graph builder read. Dependencies
are `FS` and `SS`, both resolved in the readiness check. The generator's contract is exactly the set
of blueprints `Blueprint.validate()` accepts, as tightened by ADR-0005.

**Access.** `Orchestrator._build_graph` is extracted to a module-level `build_task_graph` function so
tests exercise the real graph construction with no orchestrator, transport or storage involved.

**Run model.** A run is driven by a generated permutation of task IDs used as a priority order: the
simulation repeatedly dispatches every ready task and completes whichever running task ranks highest.
This keeps runs deterministic and makes arrival-order independence directly expressible as running
one blueprint under two orders and comparing final state.

**Outcomes.** Core properties draw completions from `SUCCEEDED` and `SKIPPED`, which the scheduler
treats identically, so the strong claim that every task ends in a terminal state survives. `FAILED`
gets its own property with the weaker honest claim: any task left non-terminal has a failed ancestor.

**Held back deliberately.** `FF` dependencies, composite and inner blueprints, scopes, task IO and
serialisation round-trips, and orchestrator-level reset and skip. `FF` in particular is excluded from
the general generator because its failure mode is a non-terminating run, which is the hardest thing
to attribute when several mechanisms are in play; it gets a narrow property of its own later.

**Configuration.** Hypothesis defaults, with the per-example deadline disabled on simulation
properties so a slow CI runner cannot produce a spurious failure. No profiles and no committed
example database until there is evidence either is needed.

## Consequences

- Scheduler properties run as fast as ordinary unit tests, because nothing below them touches a
  broker, a database or a thread.
- `build_task_graph` becomes independently testable, which matters: it currently adds injected
  composite edges before the referenced nodes exist, relying on `compas.Graph.add_edge` creating
  them bare and a later `add_node` call patching the attributes back in.
- The generator is written to match `validate()`, so "everything generated is valid" is a smoke test
  for the generator rather than evidence about the validator. The properties that genuinely
  discriminate are the mutations: inject a back-edge, detach a leaf, corrupt a dependency type.
- Anything a property uncovers beyond the fixes already scoped in ADR-0005 is marked `xfail` against
  a tracking issue rather than fixed in place, so the change stays reviewable and its scope is not
  set by whatever hypothesis happens to find first.

## Alternatives considered

**Series-parallel generator.** Composing chains and parallel branches recursively would mirror how
blueprints are actually authored with the `>>` operator, and nesting would map onto scopes. Rejected
because it cannot express DAGs that are not series-parallel, which excludes exactly the irregular
joins where scheduler bugs are most likely.

**Generate arbitrary edges and filter on `validate()`.** Simplest generator code, but most examples
would be discarded, hypothesis would hit its filter-health limit, and shrinking would degrade. It is
also circular: using `validate()` to define validity while trying to test `validate()`.

**A test-only graph builder.** Avoids touching production code, but it is a replica of
`_build_graph`. Once the two drift, every scheduler property validates a graph shape the orchestrator
never produces, while continuing to pass.

**Constructing a real `Orchestrator` with mocked storage and transport.** Exercises the genuine path,
but pays transport setup, storage mocking, preprocessing and a poller thread on every generated
example, and puts a background thread in a position to mutate state mid-test.

**`RuleBasedStateMachine`.** The idiomatic shape for stateful testing, with failures reported as a
replayable call sequence. Deferred rather than rejected: it is the natural home for orchestrator-level
reset and skip once the simple properties are green.
