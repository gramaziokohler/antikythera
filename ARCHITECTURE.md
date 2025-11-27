# Software Architecture

> **Summary**: Antikythera is a distributed system for orchestrating fabrication processes in architecture and construction.

---

## Terminology

* `Agent`: An entity that can run a specific type of `Task`. It can be a remote machine or a local process (e.g., OS-level process, robot control program, CNC program, microcontroller program).
* `Task`: A unit of work executed by an `Agent`. Tasks are `Nodes` in a `DAG` (Directed Acyclic Graph). Each task:
  * Functions as a state machine with states: `PENDING`, `READY`, `RUNNING`, `SUCCEEDED`, `FAILED`
  * Declaratively defines input and output data to establish dependencies between nodes
* `DAG` / `Graph`: Directed Acyclic Graph. Data structure used to represent a `Blueprint` through `Nodes` (tasks) and `Edges` (dependencies). Always contains at least two nodes: `START` and `END`, which can define data dependencies to enable graph composition.
* `Blueprint`: The highest level of abstraction in Antikythera. A blueprint describes all steps to fabricate a physical object (e.g., step-by-step assembly of timber beams). Internally represented as a `DAG` with a JSON representation.
* `Outer Blueprint`: A blueprint that contains other blueprints as sub-processes. Inner blueprints can be static (pre-defined blueprints) or dynamic (blueprints defined at runtime).
* `Behavior Tree`: A robotics-oriented representation of a decision tree for implementing control logic in semi-autonomous robot operation.
* `BSID`: Blueprint Session Identifier - a UUID that uniquely identifies a blueprint execution session. Sessions can have long running times (potentially multiple weeks).

## Technology Stack

### Core Technologies
* Python 3.12
* `MQTT` (via `compas_eve`): Transport layer for the event system, enabling distributed communication
* `compas`: Core framework, including the `DAG` implementation
* `compas_pb`: Protocol Buffers integration for COMPAS used for serialization of messages in the Agent Communication Protocol.
* `compas_model`: Model representation for fabricatable objects
* `immudb`: Immutable database for persistent data storage, chosen for its append-only nature and data integrity guarantees
* `FastAPI` + `uvicorn`: HTTP interface to the orchestrator service

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

The **orchestrator** is in charge of coordinating the execution of a **blueprint** described as a **DAG** (Directed Acyclic Graph). The DAG is composed by **tasks** in the nodes, and their dependencies in the edges. A task has a state (`PENDING`, `READY`, `RUNNING`, `SUCCEEDED`, `FAILED`), it declaratively defines input and output data so that data dependencies can be defined between nodes.

Each task is executed by an **agent**, either remote or local. The overall system has location transparency, so agents can be running in one or more machines in the same or different networks.

The orchestrator runs a single **blueprint** at a time. Each run of a blueprint is identified by a session identifier (`BSID`). Parallelism can be achieved inside the blueprint itself by using different agents. 

The orchestrator loads a **blueprint** from a file or an API call, and will begin to execute it. The link between the JSON representation and the in-memory execution should not be lost during loading, because it is necessary to allow live modifications of the running graph. Modifications of the graph are append-only operations, so that the orchestrator can always keep track of the original graph. Edge-cases like the deletion of a node should be handled with care, to gracefully deal with loss of data dependency as well as case of a agent running a node while it is deleted.

#### Orchestrator API

The orchestrator API is exposed through a FastAPI application (`python -m antikythera`). The API accepts HTTP requests to control blueprint sessions:

- `POST /blueprints/start`: Starts executing a blueprint. Payload mirrors the CLI arguments: `blueprint_file` (path to JSON blueprint), `broker_host`, and `broker_port`. The response returns the generated `session_id`.
- `GET /blueprints`: Lists active sessions with their blueprint path, broker configuration, and start timestamp so that operators can track concurrent executions.

Sessions remain active until the process receives a shutdown signal, at which point the API shuts down all orchestrators gracefully.

### Agents

An **agent** is an entity that can run a specific type of **task**.

Python agents are implemented as subclasses of the `Agent` base class and use decorators to define their capabilities, however, it is possible to implement agents in other languages, provided they adhere to the **Agent Communication Protocol**.

Agents can run locally or remotely. Agents don't explicitely send or receive MQTT messages. Their lifetime is controlled by an agent manager process that takes care of instantiating and disposing agents as needed, as well as triggering task execution. The agent manager is also in charge of handling the termination of the orchestrator and disposing of all agents.

For simplicity, a simple launcher can be used to start one agent manager for each agent type defined in a blueprint.

#### Python Agents

A base class for Python agents is provided to simplify development. Agents are registered used a class decorator, and their capabilities (tools) are defined using method decorators. Below is an example of a simple agent that can handle two types of tasks: `system.start` and `system.sleep`.

```python
from antikythera_agents import Agent, agent, tool
from antikythera.models import Task

@agent(type="system")
class SystemAgent(Agent):
    def __init__(self):
        super().__init__()
        self.start_time = time.time()
    
    def dispose(self):
        super().dispose()
    
    @tool(name="start")
    def start_process(self, task: Task) -> dict:
        # ...
        return {"process_start_time": time.time()}
    
    @tool(name="sleep")
    def sleep_process(self, task: Task) -> dict:
        duration = task.params.get("duration", 1)
        time.sleep(duration)
        return {"slept_duration": duration}
```

#### Development Mode

The agent launcher supports a development mode that enables hot reloading of agents when their source code changes. This is useful for rapid development and testing of new agent capabilities.

To enable development mode, start the launcher with the `--dev` flag:

```bash
python -m antikythera_agents --dev
```

When enabled, the system watches for changes in the source files of loaded agents and automatically reloads them without restarting the process.

#### Error Handling and Recovery

If a task ends up in a failed state, the orchestrator should be able to resume execution from that point. This topic is not yet addressed but will require tasks to define retry policies and idempotency, i.e. if a task can be run multiple times without side effects, and if they can be retried in case of failure. For the time being, a failed task will cause the orchestrator to stop the session.

Initially, only very simple agents will be implemented to execute toy problems.

### Data store

The system uses a [`ImmuDB`](https://immudb.io/) as persistent data store to keep track of state. The data store is used to store the state of the **orchestrator** itself, and the state of the **blueprint**.

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
        "result1": "All COMPAS-serializable types are supported via compas_pb: primitives, geometry objects, data structures, and custom objects."
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

#### Argument mapping

Tasks can optionally declare an `argument_mapping` block to remap task-level input/output names to the names used in blueprint session data. This helps avoid key collisions and lets an agent-specific signature stay stable while the surrounding blueprint uses different data keys.

```json
{
  "id": "calculate_ik",
  "type": "moveit_planner.pnp_",
  "inputs": {
    "start_state": "compas_fab.robots.RobotCellState"
  },
  "outputs": {
    "grasp_frame": "compas.geometry.Frame"
  },
  "argument_mapping": {
    "inputs": {
      "start_state": "some_blueprint_state_name"
    },
    "outputs": {
      "grasp_frame": "framecito"
    }
  }
}
```

### Agent Communication Protocol

Agents communicate with the orchestrator via 4 types of messages sent over MQTT. The schema for these protocol messages are defined using Protocol Buffers (`protobuf`) and the `compas_pb` library for type-safe serialization of COMPAS objects:

1. **Task Assignment**: The orchestrator sends a `TaskAssignmentMessage` when a task is ready to be executed.
2. **Task Status Updates**: When an agent begins executing a task it publishes a `TaskStatusUpdateMessage` so the orchestrator know the task is now actively running and who is responsible for it. After this, the agent may send additional status updates (e.g., progress reports) as needed.
3. **Task Completion**: The agent sends a `TaskCompletionMessage` with the task result upon completion (success or failure).
4. **Task Completion ACK**: The orchestrator sends a `TaskCompletionAckMessage` immediately after it accepts a `TaskCompletionMessage`. This acknowledgement is broadcast to all agents running the same task so the non-reporting agents can invalidate their local execution and return to the idle state without waiting for a timeout.

**Protocol Buffer Definitions**

The complete protobuf schema is maintained in [`src/antikythera/proto/antikythera.proto`](src/antikythera/proto/antikythera.proto).

**Key message types:**
- `TaskAssignmentMessage`: Sent by orchestrator to agents when tasks are ready
- `TaskStatusUpdateMessage`: Sent by agents as soon as they start working on a task
- `TaskCompletionMessage`: Sent by agents to orchestrator upon task completion
- `TaskCompletionAckMessage`: Sent by orchestrator after recording task completion to signal that the task is closed for all agents
- `TaskState`: Enum defining task lifecycle states
- `TaskError`: Error information for failed tasks

**Message structure overview:**
```protobuf
// Canonical definitions in src/antikythera/proto/antikythera.proto
package antikythera.v1;

message TaskAssignmentMessage {
  string id = 1;                                    // Required: unique task identifier
  string type = 2;                                  // Required: task type (determines which agent handles it)
  map<string, compas_pb.data.AnyData> inputs = 3;   // Optional: task inputs from blueprint session data
  repeated string output_keys = 4;                  // Optional: expected output keys (for validation)
  map<string, compas_pb.data.AnyData> params = 5;   // Optional: task-specific parameters (not from session data)
  google.protobuf.Timestamp timestamp = 6;          // Optional: assignment timestamp
}

message TaskStatusUpdateMessage {
  string id = 1;                                    // Required: task identifier
  TaskState state = 2;                              // Required: typically TASK_STATE_RUNNING when execution starts
  string agent_id = 3;                              // Required: agent claiming the task
  compas_pb.data.AnyData data = 4;                  // Optional: any additional status data (e.g., progress)
  google.protobuf.Timestamp timestamp = 5;          // Optional: update emission time
}

message TaskCompletionMessage {
  
  string id = 1;                                    // Required: unique task identifier
  TaskState state = 2;                              // Required: current task state
  map<string, compas_pb.data.AnyData> outputs = 3;  // Optional: task outputs (only for succeeded tasks)
  TaskError error = 4;                              // Optional: error information (required for failed tasks)
  google.protobuf.Timestamp timestamp = 5;          // Optional: message timestamp
  uint64 duration_ms = 6;                           // Optional: task execution duration in milliseconds
}

message TaskCompletionAckMessage {
  string id = 1;                                    // Required: task identifier being acknowledged
  TaskState state = 2;                              // Optional: final recorded state (SUCCEEDED/FAILED)
  string accepted_agent_id = 3;                     // Optional: agent whose completion was accepted
  google.protobuf.Timestamp timestamp = 4;          // Optional: time the orchestrator processed the completion
}

enum TaskState {
  TASK_STATE_UNSPECIFIED = 0;
  TASK_STATE_PENDING = 1;
  TASK_STATE_READY = 2;
  TASK_STATE_RUNNING = 3;
  TASK_STATE_SUCCEEDED = 4;
  TASK_STATE_FAILED = 5;
}
```

**Integration with `compas_pb`:**

Task inputs and outputs leverage `compas_pb` for type-safe serialization of any COMPAS-serializable type:
- **Primitives**: `str`, `int`, `float`, `bool` → serialized via `google.protobuf.Any`
- **COMPAS Data types**: `Point`, `Vector`, `Frame`, `Plane`, `Box`, `Mesh`, etc. → dedicated protobuf messages (`PointData`, `VectorData`, etc.)
- **Collections**: `list`, `dict` → `ListData`, `DictData` messages from `compas_pb`
- **Custom objects**: Any object implementing COMPAS serialization protocol → `AnyData` container


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

Antikythera is designed to be extensible. Custom agents can be implemented in separate repositories and languages, provided they adhere to the **Agent Communication Protocol**. The system supports:

- Python-based agents using the provided base classes and `compas_pb` serialization
- External agents communicating via MQTT using the defined protobuf message schemas

## Roadmap

- **M1 (Toy problem 1):** author a trivial blueprint composed by 3 tasks (A1, A2, B1) + 1 start and 1 end task. A1 and A2 depend on START, B1 depends on A1 and A2, END depends on B1. A1 will wait for user input on the terminal (or any other input method) and define one output data key. A2 will be a "sleep 5 seconds" task, B1 will define a data input on the output key generated by A1 and print it.
- **M2 (Toy problem 2):**: author a blueprint for robotic pick and place of a single element using a 6-DoF robot (ABB GoFa robot model) composed by 7 tasks: A1: plan trajectory, A2: move/execute trajectory, A3: actuate gripper, A4: plan trajectory, A5: move/execute trajectory. All tasks are sequential and depend on the previous one. START and END are placed at the start and end of the blueprint respectively. The `move/execute trajectory` tasks should implement `needs_approval`. This means, there are 3 new agent types: `compas_fab.plan_trajectory` (used to calculate approach and retract trajectories), `compas_rrc.move_to_trajectory` and `compas_rrc.actuate_gripper`.
- **M4 (Toy problem 4):**: Inner blueprints using `system.composite` (static): 1) Implement static inner blueprint and agent, 2) Inputs and Outputs of inner blueprints.
- **M5 (Toy problem 5):** Pick and place for a single element using a 6-DoF robot with inner blueprints. Tasks: 1) `Plan Pick` and `Plan Place` for `MoveIt` planner agent. 2) For next Milestote: Model is read-only and globally accessible inside inner blueprints, but the element sequencer will assign additional information: current element id + list of state (built/not built) of all elements.
- **M6 (Toy problem 6):**: Add `compas_model` to M5, including element ids referenced from tasks and dynamic inner blueprint expansion based on calls to some kind of sequencer (sequencing the model's elements).


* Two possible levels of agents (can both exist in Antikythera):
 - Type 1: Simple wrapper for some Python code (e.g. inverse_kinematics(config) -> Frame, forward_kinematics(Frame) -> config)
 - Type 2: Process-aware/model-aware/scene-aware: mindful agents


- Model -> Element -> FabricationElement
- Sequencer:
  - sequence_the_model(model) -> list[FabItem]
- FabItem:
  - id: str
  - geometry: compas.geometry.Geometry
  - element_id | stock_id | other_things
  - state: enum (NOT_STARTED, IN_PROGRESS, COMPLETED)
  - fabrication_instructions: dict


## TODOs

- [ ] Implement compas.data support for parameters
- [ ] 
