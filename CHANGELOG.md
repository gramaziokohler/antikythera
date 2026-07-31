# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

### Changed

* Renamed `type` to `type_hint` on task inputs, outputs and params (`TaskIO` and subclasses) to disambiguate it from a task's `type` (agent.tool). Blueprint JSON accepts either key on load and always emits `type_hint`; `type` is a deprecated alias and a `type` property is kept for in-process readers. See ADR-0003.
* **Breaking:** `antikythera-agents` now requires an explicit subcommand. `antikythera-agents run` starts the launcher with the same flags the bare command used to accept (`--broker-host`, `--broker-port`, `--dev`, `--sys-only`); invoking `antikythera-agents` with no subcommand exits non-zero with usage text instead of starting the launcher. Argument parsing moved into the `cli` module, leaving `__main__` as a thin entry point.
* Tool signatures now bind task inputs, not just params: an unannotated parameter (or one explicitly marked `Input[T]`) binds by name from `task.inputs`. Binding is strict — a required input the task doesn't supply, an input the task declares that the tool doesn't accept, or a non-optional input resolving to `None` all fail the task before the tool runs, reported as `TaskError(code="TOOL_BINDING_ERROR")` rather than the blanket `TOOL_FAILURE`. `Task`-typed (opaque) tools are exempt. See ADR-0002.
* **Breaking:** `io.copy` now declares `source` and `destination` as task inputs instead of reading them from either input or param; blueprints must wire them as inputs (literal value or `get_from`).
* A tool parameter can be annotated `Context[T]` to bind by name from the task's expansion context (`task.context`) — the identity of the item a dynamically expanded inner blueprint is working on, distinct from `ExecutionContext`. A required context key absent from `task.context` raises `ToolBindingError`, naming the key. The catalog reports these under `requires_context`. See ADR-0002.
* A tool whose return type is a `TypedDict` has its returned dict checked against it: a declared key missing from the result fails the task with `ToolBindingError`, naming the key; a key marked `NotRequired` may be absent without error. The catalog reports each output's `type_hint` and `optional`. Tools taking `Task`, and tools returning a plain `dict`/`Dict[str, Any]`, are exempt — `system.composite` stays opaque permanently. See ADR-0002.
* A bound value is now checked against a plain-class annotation (`Frame`, `str`, ...) on inputs, params and context values alike, failing with `ToolBindingError` naming the argument and the expected/actual type on mismatch. Parameterised generics (`list[X]`, ...) are not checked. `int`/`float` bind leniently in both directions to absorb the widening `compas_pb` deserialisation can introduce. Opaque tools are exempt. See ADR-0002.

### Removed


## [0.4.1] 2026-07-07

### Added

### Changed

* Fixed session fails when COMPAS types are used in task data.

### Removed


## [0.4.0] 2026-07-02

### Added

- Orchestrator-side re-dispatch polling loop: unclaimed `READY` tasks are re-published with exponential backoff (`min(base * 2^attempts, max)`) and failed with error code `NO_AGENT_CLAIMED` after `MAX_REDISPATCHES` attempts. Configurable via `REDISPATCH_BASE_DELAY` (default 2 s), `REDISPATCH_MAX_DELAY` (default 90 s), and `MAX_REDISPATCHES` (default 5) env vars.
- `GET /sessions/{id}/stream` SSE endpoint that pushes `task_state_changed` and `session_state_changed` events as the orchestrator transitions state.
- `datastore_updated` SSE event emitted after each task that writes outputs, carrying enriched `blueprint_id` + `data` payload.

### Changed

* Changed `compas_timber` from pre-release to `>=2.1.2` in requirements.txt.
* Fixed session state gets overwritten to `STOPPED` instead of `SUCCESS` or `FAILED`.
* Fixed orchestrator stays subscribed after session failure. 

### Removed


## [0.3.1] 2026-05-19

### Added

- Added MCP Server service to dev docker compose file.

### Changed

- Outputs from failed tasks are disregarded as to not overwrite valid data in session data.
- Fixed MCP server fails to start when using sse as transport.
- Bumped min `compas_eve` version to `2.3.0`.
- Added passthrough transport and tls to agent launcher.


### Removed


## [0.3.0] 2026-04-24

### Added

- Added MCP server.....
- Added `invoke docker` which builds both images

### Changed

- Fixed scope reset behavior
- Allow deleting sessions which are still in-memory

### Removed


## [0.2.0] 2026-04-20

### Added

### Changed

### Removed


## [0.1.2] 2026-04-17

### Added

### Changed

### Removed


## [0.1.1] 2026-04-17

### Added

### Changed

### Removed


## [0.1.0] 2026-04-17

### Added
- Named sessions: new session API endpoint accepts an optional session name.
- API endpoint to remove/delete sessions.
- `--sys-only` flag to agent launcher to restrict to system agents only.
- MQTT traffic dumper script decodes protobuf messages; now continuously flushes entries to file.
- `compas_timber` added to Docker image.
- **Scopes**: new scope mechanism for controlling looping/retry/skip behavior within blueprints.
  - `scope_start` / `scope_end` task properties define contiguous DAG regions.
  - Three policies: **skip** (condition-gated), **retry** (fixed N retries), **while** (condition-based loop with optional iteration cap).
  - Scopes are identified by the opening task's ID; `scope_end` references that ID.
  - Blueprint validation ensures matched start/end pairs with no interlaced scopes.
  - New `ScopeRegistry` and `Scope` classes in `antikythera_orchestrator.scopes`.
- Updated blueprint JSON schema with `scope_start`, `scope_end`, `RetryPolicy`, and `WhilePolicy` definitions.
- Example blueprints for scope skip, retry, and while policies.
- Unit tests for all scope policies (skip, retry, while, max_iterations).

### Changed
- Swapped NanoMQ for Eclipse Mosquitto as the MQTT broker.
- Migrated storage backend from immudb to Redis.
- Agent launcher now uses logging instead of print statements; launcher errors during task execution are caught and reported as task failures.
- Fixed static composite task execution.
- `on_task_claim`: check `task is None` instead of `task_id is None` to correctly handle unknown task IDs.
- Session state writes to storage are now wrapped in try/except to prevent secondary failures from masking the original error.
- Added debug logging in strategic places across the orchestrator scheduling path.
- Moved immudb storage mock to shared conftest; removed obsolete storage module.
- Built Docker image for antikythera orchestrator/agents.
- Fixed broken tests after static composite fix.

### Added
- Strict validation for Blueprint JSON files, requiring explicit list-of-dictionary formats for inputs, outputs, and parameters.
- Unit tests for failed task resume scenarios, including session revival from storage.
- Add support for competitive execution of tasks.
- New API endpoint `get_blueprint_context` to get the fabrication context of a composite blueprint.
- New API endpoint `get_running_composites` to get the currently running composite blueprints.
- Add new `user_interaction.notify` agent for sending user notifications with including support for string interpolation of session data.
- Add API endpoint and backend support for reseting tasks (and downstream dependencies) to a pending state to allow re-execution after a failure or user intervention.
- Added API endpoint for skipping tasks.
- Added `TaskState.SKIP_REQUESTED` to represent tasks that have been requested to skip but are waiting for their dependencies to be met before transitioning to `SKIPPED`.
- Added a redis backend to the storage interface and places behing a unified interface in package `storage`.

### Changed
- Moved `composite_to_inner_blueprint_map` and `blueprint_contexts` from `Orchestrator` to `BlueprintSession` for proper serialization and session restoration.
- Simplified `SessionStorage` API to use `save_session()` and `load_session()` for complete session persistence instead of piecemeal updates.
- Added `load_session_with_metadata()` to `SessionStorage` for retrieving session data with storage metadata (used by `list_sessions` API).
- Added `mock_agent_discovery` fixture to orchestrator tests to prevent loading external agents during testing.
- New explicit accessor methods for `Task` values (`get_input_value`, `get_output_value`, `get_param_value`, `set_input_value`, `set_output_value`, `set_param_value`).
- New JSON Schema for strictly validating Blueprint files.
- `BlueprintJsonParser` now supports full validation and symmetric read/write of Blueprints.
- Added `proto` file to release artifacts
- Added paging to sessions list API.
- Added `max_grpc_message_length` configuration for immudb client to handle larger messages.
- Added demo agent to return the Standard 3d bunny as a COMPAS mesh.
- Added `io.copy` agent/tool to copy files with support for glob patterns.
- Do not implicitly propagate skip status to child tasks, as it generates an non-intuitive workflow where skipping a parent task causes all child tasks to be skipped without the ability to override.
- Extended the context of condition eval, so that it includes fab context and session data.
- Fixed resuming not doing anything due to tasks being in RUNNING or READY state when session was stopped.
- Fixed condition doesn't get carried over to dynamically expanded tasks.

### Changed
- Refactored `Task` class to enforce a single data access pattern.
- Changed build system to `hatchling` to hook the protobuf compilation into the build process.

### Removed
- `Task.input_values` and `Task.param_values` convenience properties have been removed to prevent ambiguity.

## [0.0.0] - Initial Capabilities

### Added
- **Orchestration**:
    - Centralized `Orchestrator` based on an **Event-Driven (MQTT)** architecture.
    - **REST (FastAPI)** for interacting with the system programmatically.
    - **Dynamic Task Expansion**: `Sequencer` system to allow runtime procedural generation of tasks based on fabrication model geometry (Based on `compas_model`).
    - **Composite & Conditional Logic**: Support for nested task groups and data-driven branching.
- **Data & Trust**:
    - **Immutable Ledger**: Data storage via `immudb` to provide a tamper-proof, cryptographically verifiable audit trail of every fabrication step.
    - **Model Management**: Native handling of **COMPAS** models, with specialized support for Stock and Element management in digital fabrication (`compas_timber`).
- **Connectivity**:
    - **Transport Agnostic**: Built on `compas_eve`, using **MQTT** for high-throughput messaging and **Protocol Buffers** for efficient serialization.
    - **REST API**: Comprehensive API for session management, blueprint uploading, and system monitoring.
- **Blueprints**:
    - JSON-based definition format for fabrication processes.
- **Agents**:
    - **Plugin System**: Fully extensible agent architecture using `@agent` decorators and auto-discovery.

