---
title: "Type checking at bind time for plain-class annotations"
type: AFK
---

## What to build

Check that a bound value is actually of the annotated type, so a blueprint wiring a `Frame`
where a `RobotCellState` is expected fails at the boundary with a clear message rather than
somewhere deep inside the tool.

Deliberately partial, because full runtime type checking is not worth its cost here:

- **Check** where the annotation is a plain class — `Frame`, `RobotCellState`, `str`, a
  custom COMPAS type.
- **Skip** parameterised generics such as `list[JointTrajectory]`. Checking element types
  means walking potentially large collections on every task, for a class of error the plain
  checks mostly catch anyway.
- **Be lenient with numerics.** Values arrive through protobuf and `compas_pb`
  deserialisation, which can widen an `int` to a `float`. A tool annotated `float` must
  accept an `int` and vice versa where the value is integral. Getting this wrong will
  produce spurious failures on blueprints that work today, so cover it with tests.

Failures use `TOOL_BINDING_ERROR` and report both the expected and the actual type.

Applies to inputs, params and context values alike. Opaque tools remain exempt.

## Acceptance criteria

- [x] A value whose type does not match a plain-class annotation fails the task, with an
      error naming the argument, the expected type and the actual type.
- [x] A parameterised generic annotation is not checked, and binds whatever it is given.
- [x] An `int` binds to a `float` annotation and an integral `float` binds to an `int`
      annotation, both without error.
- [x] `None` handling is unchanged from the input-binding rules — this issue does not alter
      when `None` is acceptable.
- [x] Checking applies to inputs, params and context values.
- [x] Opaque tools are unaffected.
- [x] A round trip through protobuf serialisation of each supported value kind binds without
      spurious type errors.

## Blocked by

- `issue-td-04-task-inputs-strict-binding`
