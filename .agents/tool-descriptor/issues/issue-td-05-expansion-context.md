---
title: "Expansion context binds via Context[T]"
type: AFK
---

## What to build

Tools inside a dynamically expanded inner blueprint need to know which item they are working
on — the `element_id`, and whatever else the sequencer attached. Today they reach into the
task's context dict by key. Give them a `Context[T]` annotation instead.

No new plumbing is required. The expansion context already flows end to end: the
orchestrator stores it per inner blueprint, packs it into the task assignment message, the
protocol carries it, and the launcher lands it on the task. Binding `Context[T]` is a lookup
in that dict.

The catalog reports these as `requires_context` — a list of names, since the value comes
from the runtime rather than from anything the blueprint author writes.

Terminology to respect: this is the **expansion context**, distinct from `ExecutionContext`,
which is the cancellation and lifecycle handle given to a running tool. Both are bindable and
they are not the same thing. See the glossary in `ARCHITECTURE.md`.

Verify against a genuinely dynamic blueprint — one where a sequencer expands a composite task
over a model's elements — not just a unit test with a hand-built task.

## Acceptance criteria

- [x] `Context[T]` is importable from the annotations module.
- [x] A parameter annotated `Context[T]` binds to the matching key in the task's context.
- [x] A tool requiring a context key that is absent fails with `TOOL_BINDING_ERROR` naming
      the key.
- [x] `Context[T]` and `ExecutionContext` parameters can coexist in one signature and bind to
      the correct things.
- [x] The catalog lists context requirements under `requires_context`.
- [x] A blueprint with a dynamically expanded composite task runs green, with each inner
      blueprint's tool receiving its own element's context.

## Blocked by

- `issue-td-03-tracer-one-tool-end-to-end`
