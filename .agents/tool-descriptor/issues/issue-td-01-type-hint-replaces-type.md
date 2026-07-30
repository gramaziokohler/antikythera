---
title: "type_hint replaces type on task inputs, outputs and params"
type: AFK
---

## What to build

A blueprint file currently uses `type` for two unrelated things: on a task it names the
agent and tool (`"type": "system.sleep"`), on an input it names a Python type
(`"type": "compas.geometry.Frame"`). Rename the data one to `type_hint` so `type` means
exactly one thing. See ADR-0003.

This is prefactoring for the tool descriptor work — the descriptor has to carry both
concepts in one object, so the ambiguity has to go first.

The rename lands behind a **tolerant reader**. `TaskIO` and its subclasses (`TaskInput`,
`TaskOutput`, `TaskParam`) accept either key on load and always emit `type_hint` when
serialising. Keep a `type` property returning `type_hint` so in-process readers keep
working. The JSON schema accepts either key and documents `type` as deprecated — note it
currently lists `type` as required for task IO, so that becomes a "one of".

Rewrite the example blueprints to use the new key.

**Explicitly out of scope**, and the reason the tolerant reader exists: the
`antikythera-frontend` repo (which reads `output.type` when rendering breakpoints),
blueprints already stored in immudb, blueprints packed inside `.cog` archives, and the MCP
server's instructions text. These migrate on their own schedule. File a follow-up to remove
the deprecated alias once they have.

## Acceptance criteria

- [x] `TaskIO`, `TaskInput`, `TaskOutput` and `TaskParam` accept `type_hint`.
- [x] They also still accept `type`, and a blueprint written with either key loads to the
      same in-memory object.
- [x] Serialisation always emits `type_hint` and never `type` for task IO.
- [x] A `type` property still returns the value, so existing in-process readers are unbroken.
- [x] The blueprint JSON schema accepts either key; `type` is documented as deprecated and
      is no longer unconditionally required.
- [x] All example blueprints use `type_hint`.
- [x] An existing blueprint using `type` still loads, executes and round-trips.
- [x] CHANGELOG records the change — this is a public API change.

## Blocked by

None — can start immediately.
