# Software Architecture

> **Summary**: Antikythera is a distributed system for orchestrating fabrication processes in architecture and construction.

---

## Terminology

* `Agent`: An entity that can run a specific type of `Task`. It can be a remote machine or a local process (e.g., OS-level process, robot control program, CNC program, microcontroller program).
* `Task`: A unit of work executed by an `Agent`. Tasks are `Nodes` in a `DAG` (Directed Acyclic Graph). Each task:
  * Functions as a state machine with states: `pending`, `ready`, `running`, `succeeded`, `failed`
  * Declaratively defines input and output data to establish dependencies between nodes
* `DAG` / `Graph`: Directed Acyclic Graph. Data structure used to represent a `Blueprint` through `Nodes` (tasks) and `Edges` (dependencies). Always contains at least two nodes: `START` and `END`, which can define data dependencies to enable graph composition.
* `Blueprint`: The highest level of abstraction in Antikythera. A blueprint describes all steps to fabricate a physical object (e.g., step-by-step assembly of timber beams). Internally represented as a `DAG` with a JSON representation.
* `Behavior Tree`: A robotics-oriented representation of a decision tree for implementing control logic in semi-autonomous robot operation.
* `BSID`: Blueprint Session Identifier - a UUID that uniquely identifies a blueprint execution session. Sessions can have long running times (potentially multiple weeks).

## Technology Stack

### Core Technologies
* Python 3.12
* `MQTT` (via `compas_eve`): Transport layer for the event system, enabling distributed communication
* `compas`: Core framework, including the `DAG` implementation
* `compas_model`: Model representation for fabricatable objects
* `immudb`: Immutable database for persistent data storage, chosen for its append-only nature and data integrity guarantees

### Integration Technologies
* `compas_fab`: Handles tasks of type **Robotic Planning** (using Project Theseus, `wip_process` branch)
* `compas_emma`: Implements tasks of type **Behavior Tree**
* `compas_rrc`: Execution backend for `compas_emma` behavior trees
* `FastMCP`: Potential implementation for tasks of type **MCP Server/tools**

The technologies above were selected to provide a balance between reliability, performance, and integration with existing COMPAS ecosystem components.

---

## High-Level Architecture

- **Orchestrator**: control-plane
- **Agents:** execution-plane
- **Data store:** data-plane
- **Observability:** TDB

## Components

### Orchestrator

The **orchestrator** is in charge of coordinating the execution of a **blueprint** described as a **DAG** (Directed Acyclic Graph). The DAG is composed by **tasks** in the nodes, and their dependencies in the edges. An task has a state (pending, ready, running, succeeded, failed), it declaratively defines input and output data so that data dependencies can be defined between nodes.

Each task is executed by an **agent**, either remote or local. The overall system has location transparency, so agents can be running in one or more machines in the same or different networks.

The orchestrator runs a single **blueprint** at a time. Each run of a blueprint is identified by a session identifier (`BSID`). Parallelism can be achieved inside the blueprint itself by using different agents. 

The orchestrator loads a **blueprint** from a file or an API call, and will begin to execute it. The link between the JSON representation and the in-memory execution should not be lost during loading, because it is necessary to allow live modifications of the running graph. Modifications of the graph are append-only operations, so that the orchestrator can always keep track of the original graph. Edge-cases like the deletion of a node should be handled with care, to gracefully deal with loss of data dependency as well as case of a agent running a node while it is deleted.

### Agents

An **agent** is an entity that can run a specific type of **task**.

Python agents are subclasses of the `Agent` class, which provides a common interface for all agents, however, it is possible to implement agents in other languages, provided they adhere to the agent communication protocol.

Agents can run locally or remotely. A minimal agent implementation is a simple class with a defined method `run(self, task: Task)` for the execution of a single task instance. One instance of an agent can run multiple tasks, so the execution of `run()` should be thread-safe.

Agents don't explicitely send or receive MQTT messages. Their lifetime is controlled by an agent manager process that takes care of instantiating and disposing agents as needed, as well as triggering the `run()` method when a notification message arrives. The agent manager is also in charge of handling the termination of the orchestrator and disposing of all agents.

For simplicity, a simple launcher can be used to start one agent manager for each agent type defined in a blueprint.

If a task ends up in a failed state, the orchestrator should be able to resume execution from that point. This topic is not yet addressed but will require tasks to define if they are idempotent, i.e. if they can be run multiple times without side effects, and if they can be retried in case of failure. For the time being, a failed task will cause the orchestrator to stop the session.

Initially, only very simple agents will be implemented to execute toy problems.

### Data store

The system uses a persistent data store to keep track of state. The data store is used to store the state of the **orchestrator** itself, and the state of the **blueprint**.

The data store contains two types of data, internal and external:
* Orchestrator data, considered internal.
* Blueprint session data, considered external and linked to a specific `BSID` (blueprint session identifier).

The global nature of blueprint session data is mitigated by the data dependencies defined in the **DAG**, i.e. by defining input and output data keys declaratively.

### Observability

TBD

---

## File formats

### Blueprint Definition

The blueprint is defined in a structured JSON format. The schema is under development, but will include:

```json
{
  "version": "1.0",
  "id": "toy-problem-1",
  "name": "Toy Problem 1",
  "description": "A sample blueprint definition",
  "tasks": [
    {
      "id": "start",
      "type": "system.start",
      "outputs": {
        "start_time": "timestamp"
      }
    },
    {
      "id": "A1",
      "type": "user_interaction.user_input",
      "description": "Wait for user input",
      "outputs": {
        "result1": "str"
      },
      "depends_on": [
        {"id": "start"}
      ],
      "_docs": {
        "result1": "Types are only primitives: str, int, float, bool, timestamp, bytes."
      }
    },
    {
      "id": "A2",
      "type": "system.sleep",
      "description": "Sleep for 5 seconds",
      "duration": 5,
      "depends_on": [
        {"id": "start"}
      ],
      "_docs": {
        "duration": "Duration in seconds. This is a task parameter, not an input from blueprint session data."
      }
    },
    {
      "id": "B1",
      "type": "user_interaction.user_output",
      "description": "Print result",
      "inputs": {
        "result1": "str"
      },
      "depends_on": [
        {"id": "A1", "type": "FS"},
        {"id": "A2", "type": "FS"}
      ]
    },
    {
      "id": "end",
      "type": "system.end",
      "outputs": {
        "end_time": "timestamp"
      },
      "depends_on": [
        {"id": "B1"}
      ]
    }
  ]
}
```

This schema will evolve as the system matures.

## Authoring Surface

The authoring interface for blueprints will evolve through three phases:

### Phase 1: JSON-Based Definition (Current)

Initially, blueprints are defined using the JSON format described above. This provides a structured, machine-readable representation that can be validated and executed by the system.

### Phase 2: Python DSL

A domain-specific language (DSL) implemented in Python will provide a more ergonomic interface for defining blueprints programmatically. This will enable:

- Type checking and validation during development
- Reuse of process components and patterns
- Integration with existing Python-based workflows

### Phase 3: LLM-Assisted Authoring (Long-term Vision)

In the ideal long-term vision, an LLM-based frontend will enable definition of blueprints in natural language. This system will:

1. Accept natural language descriptions of blueprints
2. Incorporate structured data inputs:
   - COMPAS Model of the fabricatable object
   - Model(s) of fabrication environments (e.g., a `RobotCell` for robotic fabrication)
3. Generate a formal **Blueprint** definition
4. Support iterative refinement through natural language interaction

The expansion from prototypical blueprints to more deterministic or algorithmic results will be handled by MCP tools, maintaining a separation between high-level blueprint definition and low-level execution details.

---

## Development

### Coding Guidelines

The project follows these coding guidelines:

- **Style**: PEP 8
- **Linter/Formatter**: `ruff`
- **Line Length**: 179 characters
- **Imports**: Single line imports. The public API of this project should always use 2nd level imports (eg. `from antikythera.models import Blueprint`) and occassionally 1st level imports (eg. `from antikythera import SomethingCore`), but never more than 2nd level imports
- **Docstrings**: NumPy style
- **Testing**: `pytest`


### Repository Structure

The Antikythera project is organized as follows:

- **`antikythera/`**: Core package containing the orchestrator implementation
  - **`orchestrator/`**: Main orchestration engine components
  - **`models/`**: Data models and schemas

- **`antikythera_agents/`**: Built-in agent implementations

### Extension Points

Antikythera is designed to be extensible. Custom agents can be implemented in separate repositories and languages, provided they adhere to the agent communication protocol. The system supports:

- Python-based agents using the provided base classes
- External agents communicating via MQTT

## Roadmap

- **M1 (Toy problem 1):** author a trivial blueprint composed by 3 tasks (A1, A2, B1) + 1 start and 1 end task. A1 and A2 depend on START, B1 depends on A1 and A2, END depends on B1. A1 will wait for user input on the terminal (or any other input method) and define one output data key. A2 will be a "sleep 5 seconds" task, B1 will define a data input on the output key generated by A1 and print it.
- **M2 (Toy problem 2):**: author a blueprint for robotic pick and place of a single element using a 6-DoF robot (ABB GoFa robot model) composed by 7 tasks: A1: plan trajectory, A2: move/execute trajectory, A3: actuate gripper, A4: plan trajectory, A5: move/execute trajectory. All tasks are sequential and depend on the previous one. START and END are placed at the start and end of the blueprint respectively. The `move/execute trajectory` tasks should implement `needs_approval`. This means, there are 3 new agent types: `compas_fab.plan_trajectory` (used to calculate approach and retract trajectories), `compas_rrc.move_to_trajectory` and `compas_rrc.actuate_gripper`.
- **M3**: Add `compas_model` to the trivial blueprint, including element ids referenced from tasks.
- **M4**: TBD
