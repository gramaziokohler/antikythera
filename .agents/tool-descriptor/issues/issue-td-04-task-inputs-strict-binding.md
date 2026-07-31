---
title: "Task inputs bind by name, strictly"
type: AFK
---

## What to build

Extend the binder to task inputs — the largest category, and the one where the failures
being fixed actually live.

An unannotated parameter is a task input. `Input[T]` is available for authors who want to
say so explicitly.

Binding is **strict**, and each violation fails the task before the tool body runs:

- a required argument the task does not supply
- an input the task declares that the tool does not accept
- a non-optional input resolving to `None`

Strictness exists because two silent failures are live today. When a remapped input key is
absent from session storage, the input currently binds as `None` and the tool proceeds; the
mistake then surfaces in some unrelated downstream task. A parameter annotated `Optional[T]`
or carrying a default legitimately accepts nothing and is exempt.

Note that a task input may carry a **static literal value** — the orchestrator falls back to
it when the key is absent from session storage and no `get_from` is set. Constants therefore
do not need to be task params, which is what makes `io.copy` migratable.

Binding failures need their own error code (`TOOL_BINDING_ERROR`) rather than the blanket
`TOOL_FAILURE` currently reported for everything, whose message blames the tool. A wiring
mismatch is the blueprint's fault, and the error should say so — naming the offending
argument, and for an unresolved input, the `get_from` key that produced nothing.

Migrate `io.copy` as proof. It currently reads `source` and `destination` from *input or
param, whichever is present*; under the new scheme each argument is one or the other, so
both become plain inputs.

**Expected fallout, and correct:** if an upstream task is skipped by a `condition`, a
downstream consumer now receives `None` and fails rather than coasting. `ARCHITECTURE.md`
describes skip propagation in the multi-parent case as "logic TBD"; this will make any gap
there visible. Report what you find rather than working around it.

## Acceptance criteria

- [x] An unannotated tool parameter binds to the task input of the same name.
- [x] `Input[T]` is importable and binds identically.
- [x] A required argument the task does not supply fails the task before the tool runs.
- [x] An input the task declares that the tool does not accept fails the task.
- [x] A non-optional input resolving to `None` fails the task, and the error names the key
      and its `get_from` mapping.
- [x] A parameter annotated `Optional[T]` or carrying a default accepts `None` without error.
- [x] An input carrying a static literal value binds to that value.
- [x] Binding failures report `TOOL_BINDING_ERROR`, distinct from `TOOL_FAILURE`, with a
      message naming the offending argument.
- [x] Tools taking `Task` remain exempt from all of the above.
- [ ] `io.copy` declares `source` and `destination` as inputs and works with both literal
      values and wired-up upstream outputs.
- [x] The catalog lists inputs with their `type_hint` and optionality.

## Blocked by

- `issue-td-03-tracer-one-tool-end-to-end`
