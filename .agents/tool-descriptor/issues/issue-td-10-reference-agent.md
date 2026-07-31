---
title: "Reference agent demonstrating the full tool convention"
type: AFK
---

## What to build

An agent whose job is to exercise and demonstrate every part of the tool convention. It
serves two purposes: the worked example agent authors copy from, and the integration fixture
that proves the binder handles combinations no first-party tool does.

It exists because the first-party tools are a poor proving ground. Of the registered tools,
only a handful can migrate at all — the rest are genuinely dynamic — and those that can take
almost no inputs between them. The interesting signatures live in project-specific agents
outside this repository. Without this agent, the binder ships exercised by one parameter and
two strings.

Cover, across a small number of tools:

- a plain task input, and one declared explicitly with `Input[T]`
- a `Param[T]`, with and without a default
- a `Context[T]` value
- an `Optional[T]` input that legitimately accepts nothing
- a `TypedDict` return with both required and `NotRequired` keys
- a tool that takes `Task` — the opaque escape hatch
- a tool that takes `ExecutionContext` and checks for cancellation
- fully filled-in NumPy docstrings, so the catalog entry shows descriptions

Keep it dependency-free — no ROS, no heavy imports — so it runs in CI. Ship an example
blueprint that drives it end to end.

Remember that parameters without defaults must precede those with them.

## Acceptance criteria

- [x] A reference agent is registered and discoverable.
- [x] Between its tools it exercises every annotation kind, defaults, `Optional`,
      `NotRequired` outputs, the `Task` escape hatch and `ExecutionContext`.
- [x] It has no dependency that prevents it running in CI.
- [x] An example blueprint drives it end to end and runs green.
- [x] `describe` produces a catalog entry for it showing inputs, params, context
      requirements, outputs with optionality, and per-field descriptions.
- [x] Integration tests assert each strict-binding failure mode against it: missing required
      argument, unexpected input, unresolved `None`, missing declared output.
- [x] It is referenced from the documentation as the worked example.

## Blocked by

- `issue-td-04-task-inputs-strict-binding`
- `issue-td-05-expansion-context`
- `issue-td-06-strict-output-enforcement`
