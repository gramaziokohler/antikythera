---
title: "Migrate remaining first-party tools, and settle which stay opaque"
type: AFK
---

## What to build

Finish the first-party migration and record, deliberately, which tools stay opaque forever.
The built-in agents are what people copy, so they should be exemplary — including where the
exemplary choice is to keep taking the whole `Task`.

**Migrate:** `system.start`, `system.end`, `system.demo_mesh` — all trivial, none take inputs,
each gains a `TypedDict` return so its outputs appear in the catalog.

**Decide:** `user_interaction.notify` is the only genuinely ambiguous case. It reads each of
its values from input-or-param-whichever-is-present, and interpolates its title and message
against arbitrary keys from the expansion context. Under the new scheme each argument is one
thing or the other, and arbitrary context access has no annotation. Either migrate it with
its behaviour narrowed — and say so in the CHANGELOG, since blueprints in the wild use it —
or keep the `Task` escape hatch and record why. Both are defensible; make the call explicitly
rather than by default.

**Leave opaque, and document why in their docstrings** so nobody "fixes" them later:

- `system.composite` — returns whatever outputs the blueprint declares
- `user_interaction.user_input` — builds its result by iterating the task's declared outputs
- `user_interaction.user_output` — iterates the task's declared inputs and accepts anything

These are not unmigrated leftovers. They are tools whose shape is genuinely determined by the
blueprint rather than the tool, which is the case the opaque escape hatch exists for.

## Acceptance criteria

- [x] `system.start`, `system.end` and `system.demo_mesh` declare `TypedDict` returns and
      appear in the catalog with their outputs.
- [x] A decision on `notify` is made, implemented, and recorded — in the CHANGELOG if its
      behaviour narrows, in a docstring if it stays opaque.
- [x] `system.composite`, `user_interaction.user_input` and `user_interaction.user_output`
      each carry a docstring explaining why they take `Task` and must stay that way.
- [x] Every example blueprint still runs green.
- [x] `describe` shows no tool that is opaque merely because nobody got round to it.

## Blocked by

- `issue-td-04-task-inputs-strict-binding`
