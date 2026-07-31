---
title: "Declared outputs are enforced against what the tool returns"
type: AFK
---

## What to build

The other half of strict binding. A tool's return type is a `TypedDict` declaring what it
produces; enforce that the returned dict matches it.

This fixes a live silent failure. An output a blueprint declares but the tool never returns
currently keeps a value of `None`, and that `None` is persisted into session data as though
it were a real result. Separately, a tool returning a key nobody declared has it appended and
persisted anyway. In both directions the mistake surfaces later, somewhere unrelated.

Rules:

- A key declared in the `TypedDict` and missing from the returned dict fails the task.
- `NotRequired[...]` marks a key optional — absent is fine, and the catalog reports it as
  `optional`.
- Tools returning a plain dict type, and tools taking `Task`, are opaque and exempt. This is
  not just a compatibility shim: `system.composite` returns whatever outputs the blueprint
  declares and can never have a fixed return type. It stays opaque permanently.

Failures use `TOOL_BINDING_ERROR` and name the missing key.

## Acceptance criteria

- [x] A tool whose return type is a `TypedDict` has its returned dict checked against it.
- [x] A declared key missing from the returned dict fails the task, naming the key.
- [x] A key marked `NotRequired` may be absent without error.
- [x] The catalog marks `NotRequired` outputs as `optional` and required ones as not.
- [x] A tool returning a plain dict type is exempt, and its catalog entry carries no output
      detail.
- [x] `system.composite` continues to work unchanged, returning output keys derived from the
      blueprint.

## Blocked by

- `issue-td-03-tracer-one-tool-end-to-end`
