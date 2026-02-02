# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Strict validation for Blueprint JSON files, requiring explicit list-of-dictionary formats for inputs, outputs, and parameters.
- New explicit accessor methods for `Task` values (`get_input_value`, `get_output_value`, `get_param_value`, `set_input_value`, `set_output_value`, `set_param_value`).
- New JSON Schema for strictly validating Blueprint files.
- `BlueprintJsonParser` now supports full validation and symmetric read/write of Blueprints.
- Added paging to sessions list API.

### Changed
- Refactored `Task` class to enforce a single data access pattern.

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

