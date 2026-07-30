---
title: "Tracer: one annotated tool binds and describes end to end"
type: AFK
---

## What to build

The thinnest complete path through every layer of the tool descriptor design: a tool
declares a typed signature, the agent binds arguments from it at execution time, and
`describe` publishes the same metadata. Narrow on purpose — one parameter kind, one tool —
but end to end and demoable. Subsequent issues widen it.

See ADR-0002. The core idea is that the signature is the single source of truth: the same
introspected object binds at runtime and produces the published descriptor, so a descriptor
that is wrong is also a tool that does not run.

**Scope of this slice:**

- A new annotations module exporting `Param[T]` (only — `Input` and `Context` come later).
  These are deliberately *not* named `TaskInput` / `TaskParam`, which are existing
  serialisable model classes appearing in blueprint JSON.
- A `ToolDescriptor` built by the `@tool` decorator from the function signature. It resolves
  type hints **lazily on first access**, never at decoration time — `get_type_hints()` fails
  on forward references and on modules using `from __future__ import annotations`, and agent
  modules are exactly where that bites.
- `Agent.execute_task` binds arguments from the descriptor, replacing the current
  arity-based dispatch (which decides whether to pass an `ExecutionContext` by counting
  parameters).
- **`Task` and `ExecutionContext` are bindable by annotation.** This is load-bearing: it
  makes every existing tool a valid new-style tool, so all currently registered tools keep
  working untouched. A tool taking `Task` is *opaque* — no derivable inputs or outputs.
- A `describe` subcommand emitting the catalog to stdout, in the flat format documented in
  `ARCHITECTURE.md` § Agent/Tool Descriptor. `agent` is the `@agent(type=...)` value and
  `type` is `{agent_type}.{tool_name}` — the string a blueprint author writes.
- `system.sleep` migrated to the new style as proof, taking its duration as a `Param`.

**Not in this slice:** task inputs, expansion context, strict validation of any kind,
`isinstance` checks, per-field descriptions, and `describe`'s import-failure behaviour. Each
has its own issue.

Note that tool names may contain dots (one existing tool is named `pnp.calculate_ik`).
Task-type resolution splits on the first dot only, so this must keep working.

## Acceptance criteria

- [x] `Param[T]` is importable from the annotations module.
- [x] `@tool` attaches a descriptor exposing the tool name, its docstring summary, its
      parameters and its outputs.
- [x] Type hints resolve lazily and are cached; a tool in a module using
      `from __future__ import annotations` or containing a forward reference does not fail
      at import time.
- [x] `Agent.execute_task` binds arguments from the descriptor; the arity-based dispatch is
      gone.
- [x] A tool annotated `task: Task` receives the task, and one also annotated
      `context: ExecutionContext` receives both.
- [x] All currently registered tools execute unchanged, with no edits to their signatures.
- [x] `system.sleep` declares its duration as a `Param` and a blueprint using it runs green.
- [x] `antikythera-agents describe` writes a JSON catalog of every registered agent and its
      tools to stdout, in the documented flat format.
- [x] A tool taking `Task` appears in the catalog with its name and description but no input
      or output detail.
- [x] Tool names containing dots resolve to the correct tool.

## Blocked by

- `issue-td-01-type-hint-replaces-type` — the descriptor emits `type_hint`.
- `issue-td-02-cli-subcommands` — `describe` needs the subcommand structure.
