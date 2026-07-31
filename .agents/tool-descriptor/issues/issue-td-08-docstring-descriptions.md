---
title: "Per-field descriptions parsed from NumPy docstrings"
type: AFK
---

## What to build

The catalog currently gives each input and output a name and a type hint. A blueprint author
— particularly an LLM — needs prose too: what *is* this input, what does the tool expect in
it.

Take it from the docstring. The project mandates NumPy-style docstrings and ruff already
enforces the convention, so the text often already exists — `io.copy` has a filled-in
`Parameters` section today.

Parse the `Parameters` and `Returns` sections and use them to fill each field's
`description`. The tool-level description remains the docstring summary.

Write the parser by hand rather than adding a dependency; the sections are simple and this is
a core package. It must **degrade rather than fail**: a missing section, an undocumented
parameter, a documented parameter that does not exist, or a malformed block should yield no
description for the affected field and leave everything else intact. A tool whose docstring
is badly formatted must still run.

## Acceptance criteria

- [x] A parameter documented in a NumPy `Parameters` section gets that text as its
      `description` in the catalog.
- [x] Return values documented in a `Returns` section populate output descriptions.
- [x] The tool-level description is the docstring summary, unchanged.
- [x] A tool with no docstring, no `Parameters` section, or a malformed docstring produces a
      catalog entry with no field descriptions and no error.
- [x] A documented parameter that is not in the signature is ignored.
- [x] A parameter present in the signature but absent from the docstring gets no description,
      while its siblings keep theirs.
- [x] Multi-line descriptions are captured.
- [x] No new runtime dependency is added.

## Blocked by

- `issue-td-03-tracer-one-tool-end-to-end`
