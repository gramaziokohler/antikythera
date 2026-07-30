---
title: "antikythera-agents gains explicit subcommands (run)"
type: AFK
---

## What to build

`antikythera-agents` currently takes flags directly (`--broker-host`, `--broker-port`,
`--dev`, `--sys-only`) and always starts the launcher. A `describe` subcommand is coming
that prints a file and exits — a different job that should look different.

Restructure the entry point into subcommands with **no implicit default**, so
`antikythera-agents run --broker-host ...` becomes mandatory. `describe` is *not* part of
this issue; landing the restructure on its own keeps the breaking change isolated and makes
adding `describe` a trivial addition rather than a rewrite.

The argument-parsing logic belongs in the `cli` module, which currently holds only an ANSI
colour class despite its name. The entry point should become thin.

This is a **breaking change**. Every documented invocation must be updated in the same
change: `ARCHITECTURE.md` (already done as part of the design work — verify it matches),
`README.md`, `docs/installation.md`, and any `python -m antikythera_agents` examples.

## Acceptance criteria

- [x] `antikythera-agents run` starts the launcher and accepts all flags the bare command
      accepted before (`--broker-host`, `--broker-port`, `--dev`, `--sys-only`).
- [x] `antikythera-agents` with no subcommand exits non-zero with usage text rather than
      silently starting the launcher.
- [x] Argument parsing lives in the `cli` module; the entry point is thin.
- [x] Adding a second subcommand requires no further restructuring.
- [x] `README.md`, `docs/installation.md` and `ARCHITECTURE.md` show the `run` subcommand
      everywhere the launcher is invoked.
- [x] CHANGELOG records the breaking change.

## Blocked by

None — can start immediately.
