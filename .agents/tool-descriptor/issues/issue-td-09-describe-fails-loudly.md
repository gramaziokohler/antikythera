---
title: "describe fails loudly when an agent module cannot be imported"
type: AFK
---

## What to build

Plugin discovery currently swallows import failures into a warning and carries on. That is
right for the launcher — you run the agents your machine can host — and wrong for `describe`.

The catalog gets **committed to a repository and read by LLMs**, and the usual invocation
(`antikythera-agents describe > tools.json`) redirects stdout and discards stderr. On a
machine missing a heavy dependency, today's behaviour would cheerfully write a catalog
silently missing agents. A consumer cannot distinguish "this tool does not exist" from "a
dependency was missing when this file was generated" — and it will confidently author
blueprints against the gap.

So `describe` exits non-zero, writes nothing to stdout, and reports each plugin that failed
along with its exception. `--allow-partial` emits the catalog anyway, recording the gaps in a
`failed` section so the omission travels with the file.

This needs a strict variant of plugin discovery that surfaces failures rather than warning.
Launcher behaviour must not change.

**Also in scope:** the `moveit` agent module still has its `@agent` decorator commented out
while remaining declared as an entry point. It imports ROS, `compas_fab` and `compas_timber`
and registers nothing — so under this issue it becomes a hard `describe` failure on any
machine without ROS, for no benefit. Either register it or drop the entry point.

## Acceptance criteria

- [x] A plugin that fails to import causes `describe` to exit non-zero and write nothing to
      stdout.
- [x] The error names each failed plugin and its exception.
- [x] `--allow-partial` writes the catalog for the agents that did load, plus a `failed`
      section naming the others.
- [x] `describe` exits zero and writes the catalog when every plugin imports.
- [x] The launcher still starts with a broken plugin present, warning as it does today.
- [x] The `moveit` entry point is either registered or removed, and `describe` succeeds on a
      machine without ROS installed.

## Blocked by

- `issue-td-03-tracer-one-tool-end-to-end`
