# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Strict validation for Blueprint JSON files, requiring explicit list-of-dictionary formats for inputs, outputs, and parameters.
- Unit tests for failed task resume scenarios, including session revival from storage.
- Add support for competitive execution of tasks.
- New API endpoint `get_blueprint_context` to get the fabrication context of a composite blueprint.
- New API endpoint `get_running_composites` to get the currently running composite blueprints.
- Add new `user_interaction.notify` agent for sending user notifications with including support for string interpolation of session data.
- Add API endpoint and backend support for reseting tasks (and downstream dependencies) to a pending state to allow re-execution after a failure or user intervention.

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

## [0.1.0] - Initial Capabilities

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

