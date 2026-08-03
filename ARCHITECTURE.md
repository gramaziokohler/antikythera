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
* `Tool`: A single capability of an `Agent`, declared with the `@tool` decorator. A `Task` names the tool that will execute it through its `type` field, in the form `{agent_type}.{tool_name}`.
* `Tool Descriptor`: The machine-readable declaration of what a `Tool` accepts and produces, derived from its Python signature. Used to bind arguments at execution time and to publish a catalog for blueprint authors.
* `Opaque Tool`: A `Tool` that takes the whole `Task` rather than declaring named arguments. Its inputs and outputs cannot be derived, so it has no descriptor detail and is exempt from strict binding. Used where outputs are genuinely determined by the blueprint rather than the tool.
* `Expansion Context`: The identity of the item a dynamically expanded inner blueprint is working on — `element_id`, and whatever else the `Sequencer` attaches. Distinct from `ExecutionContext`, which is the cancellation and lifecycle handle given to a running tool.
* `Task Input` vs `Task Param`: An input establishes a data dependency and is normally resolved from blueprint session data (optionally remapped via `get_from`); a param is wired directly into the task and never comes from session data. Both may carry a literal value.
* `type_hint`: The Python type of a task input, output or param, as a string. Documentation for a reader, not a validated constraint — enforcement happens at bind time against the tool's annotation. Distinct from a task's `type`, which names the tool.

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

The **orchestrator** is in charge of coordinating the execution of a **blueprint** described as a **DAG** (Directed Acyclic Graph). The DAG is composed by **tasks** in the nodes, and their dependencies in the edges. A task has a state (`PENDING`, `READY`, `RUNNING`, `SUCCEEDED`, `FAILED`, `SKIPPED`, `SKIP_REQUESTED`), it declaratively defines input and output data so that data dependencies can be defined between nodes.

`SKIP_REQUESTED` is a special intermediate state used when a user manually skips a task that has not yet run. Instead of immediately marking it as `SKIPPED` (which would satisfy downstream dependencies prematurely), the task waits in `SKIP_REQUESTED` until its own dependencies are met. Once the scheduler determines it is ready to run, it is then transitioned to `SKIPPED`, ensuring correct execution order.

Each task is executed by an **agent**, either remote or local. The overall system has location transparency, so agents can be running in one or more machines in the same or different networks.

The orchestrator runs a single **blueprint** at a time. Each run of a blueprint is identified by a session identifier (`BSID`). A session has a state (`PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `STOPPED`). Parallelism can be achieved inside the blueprint itself by using different agents. 

The orchestrator loads a **blueprint** from a file or an API call, and will begin to execute it. The link between the JSON representation and the in-memory execution should not be lost during loading, because it is necessary to allow live modifications of the running graph. Modifications of the graph are append-only operations, so that the orchestrator can always keep track of the original graph. Edge-cases like the deletion of a node should be handled with care, to gracefully deal with loss of data dependency as well as case of a agent running a node while it is deleted.

#### Orchestrator API

The orchestrator API is exposed through a FastAPI application (`python -m antikythera_orchestrator`). The API accepts HTTP requests to control blueprint sessions:

**Blueprints**
- `GET /blueprints`: Lists all available blueprints in the storage.
- `POST /blueprints/upload`: Uploads a new blueprint JSON file.
- `GET /blueprints/{blueprint_id}`: Retrieves a blueprint by ID. If the blueprint is active in a session, returns the expanded version.
- `DELETE /blueprints/{blueprint_id}`: Deletes a blueprint from storage.
- `POST /blueprints/start`: Starts executing a blueprint. Payload mirrors the CLI arguments: `blueprint_id` (id to stored blueprint), `broker_host`, `broker_port`, and `params` (arbitrary parameters for the session). The response returns the generated `session_id`.

**Sessions**
- `GET /sessions`: Lists active sessions with their blueprint path, broker configuration, and start timestamp.
- `GET /sessions/{session_id}`: Returns full details of a session, including the blueprint and parameters.
- `GET /sessions/{session_id}/blueprint`: Returns the blueprint associated with the session (expanded if applicable).
- `GET /sessions/{session_id}/diagram`: Returns a Mermaid diagram representing the current execution state of the session.
- `GET /sessions/{session_id}/data`: Returns the session data (inputs/outputs) stored for the session.
- `GET /sessions/{session_id}/stream`: Server-Sent Events (SSE) stream of real-time session updates. See below.
- `POST /sessions/{session_id}/pause`: Pauses the execution of a session.
- `POST /sessions/{session_id}/start`: Resumes the execution of a session.

**SSE Stream**

`GET /sessions/{session_id}/stream` opens a `text/event-stream` connection and emits events as the orchestrator processes the session: `task_state_changed`, `session_state_changed`, and `datastore_updated` (payload includes type-enriched data, see `_enrich_data_with_types`). Implementation notes (`api.py`):

- Each connection registers an `asyncio.Queue` in a global `_sse_listeners` registry keyed by `session_id`. Orchestrator state-change callbacks (registered once per session via `_register_sse_callbacks`, called on both session start and resume) run on non-async threads and push events via `loop.call_soon_threadsafe`.
- The stream closes (sends a `None` sentinel) automatically when the session reaches a terminal state (`COMPLETED`/`FAILED`), or on client disconnect, cleaning up its queue from the registry.
- Multiple clients can subscribe to the same session concurrently; each gets its own queue and receives every event.

**Models**
- `GET /models`: Lists all available models in the storage.
- `POST /models/upload`: Uploads a `compas_model` JSON file or a `.cog` archive.
- `GET /models/{model_id}`: Retrieves a model by ID.
- `DELETE /models/{model_id}`: Deletes a model from storage.

Sessions remain active until the process receives a shutdown signal, at which point the API shuts down all orchestrators gracefully.

### Agents

An **agent** is an entity that can run a specific type of **task**.

Python agents are implemented as subclasses of the `Agent` base class and use decorators to define their capabilities, however, it is possible to implement agents in other languages, provided they adhere to the **Agent Communication Protocol**.

Agents can run locally or remotely. Agents don't explicitely send or receive MQTT messages. Their lifetime is controlled by an agent launcher process that takes care of instantiating and disposing agents as needed, as well as triggering task execution. The agent launcher is also in charge of handling the termination of the orchestrator and disposing of all agents.

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
```

#### Development Mode

Both the orchestrator and the agent launcher support a development mode that enables hot reloading when source code changes. This is useful for rapid development and testing.

To enable development mode, start the services with the `--dev` flag:

```bash
# Start orchestrator in dev mode
python -m antikythera_orchestrator --dev

# Start agent launcher in dev mode
antikythera-agents run --dev
```

Note that `antikythera-agents` takes an explicit subcommand: `run` starts the launcher, `describe` emits the tool catalog. There is no implicit default.

When enabled, the system watches for changes in the source files and automatically reloads the services. The orchestrator also enables debug-level logging in development mode.

When enabled, the system watches for changes in the source files of loaded agents and automatically reloads them without restarting the process.

#### Error Handling and Recovery

If a task ends up in a failed state, the orchestrator should be able to resume execution from that point. This topic is not yet addressed but will require tasks to define retry policies and idempotency, i.e. if a task can be run multiple times without side effects, and if they can be retried in case of failure. For the time being, a failed task will cause the orchestrator to stop the session.

Initially, only very simple agents will be implemented to execute toy problems.

### Agent/Tool Descriptor

Blueprint authors — whether human or LLM — need to know which task types are available and what inputs, outputs, and parameters each one accepts. Agents shall provide a static artifact, independent of whether any agent is currently running.

The tool's **signature is the source of truth**: the same introspected metadata both binds arguments at execution time and produces the published descriptor. A descriptor that is wrong is therefore also a tool that does not run. See [ADR-0002](docs/adr/0002-tool-signatures-are-the-source-of-truth.md).

**Schema annotation on `@tool`**

Python tools created using the provided Antikythera agent mechanisms automatically generate a descriptor from their signature, triggered by the `@tool` decorator.

If not provided, the tool's name is the function name. Arguments are task inputs by default, and are otherwise annotated to say where their value comes from: `Context[...]` for values resolved from dynamic expansion, and `Param[...]` for values wired in as task parameters. The return type is a `TypedDict`:

```python
from antikythera_agents.annotations import Context, Param
from antikythera_agents.typing_compat import NotRequired, TypedDict  # 3.9-safe re-exports

class StockPnP(TypedDict):
    stock_trajectories: list[JointTrajectory]
    flipping_trajectories: NotRequired[list[JointTrajectory]]

@tool()
def plan_stock_pnp(
    self,
    nesting: NestingResult,
    element_id: Context[str],
    clearance: Param[float] = 0.05,
) -> StockPnP:
    """Plan pick-and-place trajectories for one stock, from pickup station to CNC bed.

    Parameters
    ----------
    nesting : NestingResult
        Nesting result for the current stock.
    element_id : str
        Element currently being fabricated, supplied by dynamic expansion.
    """
```

The markers live in `antikythera_agents.annotations`. They are deliberately *not* named `TaskInput` / `TaskParam`, which are existing serialisable classes appearing in blueprint JSON.

Everything in the descriptor comes from the signature, the return type, and `__doc__` — names, type hints and optionality from the signature; per-field descriptions from the NumPy-style `Parameters` and `Returns` sections.

**Opaque tools.** A tool may still take `task: Task` and read values by key. This is bound by annotation like any other parameter, so existing tools keep working unchanged. Such a tool is *opaque*: its descriptor carries no input or output list, and strict binding does not apply to it. This is not merely a compatibility shim — some tools are genuinely dynamic. `system.composite` returns whatever outputs the blueprint declares; `user_interaction.user_input` builds its result by iterating `task.outputs`. These stay opaque permanently.

**Strict binding.** For tools that declare a signature, a mismatch between blueprint and signature fails the task at the boundary with a `TOOL_BINDING_ERROR` naming the offending key: a missing required argument, an input the tool does not accept, a non-optional input resolving to `None`, or a declared output absent from the returned dict. `isinstance` is checked where the annotation is a plain class and skipped for parameterised generics. Because opaque tools are exempt, existing blueprints come under scrutiny one migrated tool at a time.

**Agent descriptor format**

A flat JSON structure, mirroring the vocabulary of the blueprint file an author is about to write. It is *structurally similar* to the MCP tools descriptor but not MCP-compatible: MCP's `inputSchema` is JSON Schema, which has nothing meaningful to say about COMPAS types (see [ADR-0003](docs/adr/0003-type-hint-replaces-type-in-blueprint-io.md)).

Example output:
```json
[
  {
    "agent": "trajectory_planner",
    "tools": [
        {
            "name": "plan_stock_pnp",
            "type": "trajectory_planner.plan_stock_pnp",
            "description": "Plan pick-and-place trajectories for one stock, from pickup station to CNC bed.",
            "inputs": [
                { "name": "nesting", "type_hint": "NestingResult", "description": "Nesting result for the current stock." }
            ],
            "params": [
                { "name": "clearance", "type_hint": "float", "optional": true }
            ],
            "requires_context": ["element_id"],
            "outputs": [
                { "name": "stock_trajectories", "type_hint": "list[compas_robots.robots.JointTrajectory]" },
                { "name": "flipping_trajectories", "type_hint": "list[compas_robots.robots.JointTrajectory]", "optional": true }
            ]
        }
    ]
  }
]
```

`agent` is the `@agent(type=...)` value; `type` is `{agent_type}.{tool_name}` — the exact string a blueprint author writes in a task's `type` field.

A CLI subcommand imports all registered agents and emits this as a static JSON file:

```bash
antikythera-agents describe > tools.json
antikythera-agents describe --format json      # same
antikythera-agents describe --allow-partial    # see below
```

Because this artifact is committed to a repository and read by LLMs — and because the usual invocation redirects stdout, discarding stderr — `describe` **fails loudly** when an agent module cannot be imported: non-zero exit, nothing written, an error naming each failed plugin. A consumer cannot otherwise distinguish "this tool does not exist" from "a dependency was missing on the machine that generated the file". `--allow-partial` emits anyway, recording the gaps in a `failed` section.

**Runtime announcement (deferred).** The intent is for each agent launcher to also announce its descriptor over MQTT, so the orchestrator can discover agents at runtime and offer a live view of available tools. This is deferred until something consumes it. Note that it *does* require a protocol change: the launcher builds a single transport hardcoded to `ProtobufMessageCodec`, so a JSON descriptor cannot travel over it — announcing needs either a new protobuf message or a second transport with a second codec. `compas_eve` supports retained publishes, so a retained message on startup is preferable to a periodic heartbeat; it does not expose a Last Will and Testament, so presence detection would need the underlying paho client.

#### Distribution

Since agents are often project-specific, the natural distribution unit is the agent Python package itself. Projects commit a `tools.json` (generated via `antikythera-agents describe`) alongside their agent code. Blueprint authors — human or LLM — consume this file at authoring time. The MCP server could later expose it as a resource so connected LLM clients receive it automatically, and validate blueprints against it; neither is implemented yet.

No changes to the Agent Communication Protocol are required **for the static file**. The deferred runtime announcement is a separate matter, as noted above.

### Sequencers

Sequencers are responsible for the dynamic expansion of blueprints. When a `system.composite` task is marked as `dynamic`, the sequencer requested in `sequencer` is invoked to generate a set of tasks that replace the original composite task. This allows for data-driven blueprint generation, where the structure of the process depends on the input data (e.g., the number of elements in a model).

The `Sequencer` abstract base class defines the interface for all sequencers. Sequencers are registered using the `@sequencer` decorator and managed by the `SequencerRegistry`.

Available sequencers:
* `BasicSequencer` (`basic_sequencer`): Iterates over all elements of a model and creates a linear chain of static composite tasks, one for each element.
* `BasicStockSequencer` (`basic_stock_sequencer`): Iterates over the stocks defined in a nesting result and creates a linear chain of tasks.
* `BasicElementSequencer` (`basic_element_sequencer`): Iterates over the elements assigned to a specific stock (intended to be used within a blueprint expanded by `BasicStockSequencer`).

#### Dynamic Task Expansion & Output Aggregation

1.  **Expansion**: When the orchestrator encounters a task with `dynamic` parameters, it uses a **Sequencer** to generate a collection of composite tasks each with a sub-blueprint for each item in the collection.
2.  **Execution**: These sub-blueprints are executed as inner blueprints.
3.  **Output Aggregation**: Since multiple inner blueprints (one per element) are generated from a single parent task, their outputs need to be aggregated back to the parent session to avoid overwriting.
    * The orchestrator detects if an inner blueprint is part of a dynamic expansion.
    * Outputs from these inner blueprints are aggregated into a dictionary in the session storage, keyed by the `element_id`.
    * Example: If a dynamic task produces a `trajectory` output for 10 elements, the session storage will contain a single `trajectory` variable which is a dictionary: `{'element_0': Trajectory(...), 'element_1': Trajectory(...), ...}`.


### Data store

The system uses a [`ImmuDB`](https://immudb.io/) as persistent data store to keep track of state. The data store is used to store the state of the **orchestrator** itself, and the state of the **blueprint**.

The data store contains two types of data, internal and external:
* Orchestrator data, considered internal.
* Blueprint session data, considered external and linked to a specific `BSID` (blueprint session identifier).
* The data store also persistently stores "uploaded" blueprints which can be then referenced by their name/identified to start. 
* Models (see `compas_model`) are stored using a key like `model:{model_id}`.

The global nature of blueprint session data is mitigated by the data dependencies defined in the **DAG**, i.e. by defining input and output data keys declaratively.

## Observability

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
      "outputs": [
        {"name": "start_time", "type_hint": "timestamp"}
      ]
    },
    {
      "id": "A1",
      "type": "user_interaction.user_input",
      "description": "Wait for user input",
      "outputs": [
        {
          "name": "result1",
          "type": "str",
          "__doc__": "All COMPAS-serializable types are supported via compas_pb: primitives, geometry objects, data structures, and custom objects."
          }
      ],
      "depends_on": [
        {"id": "start"}
      ]
    },
    {
      "id": "A2",
      "type": "system.sleep",
      "description": "Sleep for 5 seconds",
      "params": [
        {
          "name": "duration", 
          "value": 5,
          "__doc__": "Duration in seconds. This is a task parameter, not an input from blueprint session data."
        }
      ],
      "depends_on": [
        {"id": "start"}
      ]
    },
    {
      "id": "B1",
      "type": "user_interaction.user_output",
      "description": "Print result",
      "inputs": [
        {"name": "result1", "type_hint": "str"}
      ],
      "depends_on": [
        {"id": "A1", "type": "FS"},
        {"id": "A2", "type": "FS"}
      ]
    },
    {
      "id": "end",
      "type": "system.end",
      "outputs": [
        {"name": "end_time", "type_hint": "timestamp"}
      ],
      "depends_on": [
        {"id": "B1"}
      ]
    }
  ]
}
```

This schema will evolve as the system matures.

#### Input and Output Mapping

Tasks can optionally declare a `get_from` field within their `inputs` and a `set_to` field within their `outputs` definitions to remap task-level names to the names used in blueprint session data. This helps avoid key collisions and lets an agent-specific signature stay stable while the surrounding blueprint uses different data keys.

```json
{
  "id": "calculate_ik",
  "type": "moveit_planner.pnp_",
  "inputs": [
    {"name": "start_state", "type_hint": "compas_fab.robots.RobotCellState", "get_from": "some_blueprint_state_name"}
  ],
  "outputs": [
    {"name": "grasp_frame", "type_hint": "compas.geometry.Frame", "set_to": "framecito"}
  ]
}
```

#### Conditional Execution

Tasks can optionally be skipped based on a runtime condition. This is achieved by adding a `condition` definition to the task. The `condition` value is a Python expression string that evaluates to `True` (task runs) or `False` (task is skipped).

The expression context includes:
- Task parameters (by name)
- Task inputs (by name)

**Example:**
Skip a task if the user decision was not "Yes":

```json
{
  "id": "conditional_task",
  "type": "some.task",
  "condition": "decision == 'Yes'",
  "inputs": [
    {
      "name": "decision",
      "type": "str",
      "get_from": "user_choice_from_previous_task"
    }
  ],
  "depends_on": ...
}
```

When a task is skipped:
1. Its state is set to `SKIPPED`.
2. Any downstream tasks that depend on it are also recursively skipped (unless they have other parents that are valid, logic TBD). *Currently implemented strict propagation: if any parent is skipped, the child is likely skipped or logic handles it as a non-run path.*

#### Scopes

This feature allows a blueprint author to define a task as a start/open scope task and another (downstream) task as its end/close scope task. After the execution of the end/close task, a condition determines if the execution flow should return to the start/open task (loop) or continue forward. This accomodates for re-trying a task until a condition is met, or iterating over a set of tasks until that condition is met.

- Scope definition
  - Tasks have an attributes which (optionally) mark them as start of scope and end of scope. Every scope has to have a start and an end.

- Scope policy
  - A scope is assigned a policy which defines how it is executed.
  - one of the following: 
    1. "retry" (needs extra information like max retries)
    2. "while" (executes as long as condition is true, condition can be based on any session data, including outputs from the scope itself)
    3. "conditional-skip policy" - using the existing skip condition
    4. "compensating scope" - like in saga transactions, create "negatives" of tasks to roll them back. - future work..


**Skip Policy Example**

- skip doesn't require any special policy, it's simply achieved by putting a skip condition on a scope-start task.

```json
{
  "id": "scope_start_task",
  "type": "some.task",
  "condition": "fabrication_status = 'not_finished'",  // this is the skip condition, whatever the policy is, this condition evaluating to True means the entrire scope is skipped.
  "scope_start":  {"name": "scope name"},
  "inputs": [
    ...
  ],
  "depends_on": ...
}

```

**Retry Policy Example**

```json
{
  "id": "scope_start_task",
  "type": "some.task",
  "condition": "fabrication_status = 'not_finished'",  // this is the skip condition, whatever the policy is, this condition evaluating to True means the entrire scope is skipped.
  "scope_start":  {
    "name": "scope name",
    "retry_policy": {
      "retries": 5,
      "backoff": {"constant_ms": 1000} // optional backoff timeout in ms between retries. in the future: "constant_sec", "exponential", etc.
    },
  },
  "inputs": [
    ...
  ],
  "depends_on": ...
}

```

**While Policy Example**

```json
{
  "id": "scope_start_task",
  "type": "some.task",
  "condition": "fabrication_status = 'not_finished'",  // this is the skip condition, whatever the policy is, this condition evaluating to True means the entrire scope is skipped.
  "scope_start":  {
    "name": "scope name",
    "while_policy": {
      "max_iterations": 5, // optional
      "condition": "fabrication_status = 'not_finished'"
    },
  },
  "inputs": [
    ...
  ],
  "depends_on": ...
}

```
  

### COG Archive

The `.cog` file format is a ZIP archive used to package multiple models and their associated nesting results for bulk upload.

**Structure:**
- `manifest.json`: A JSON file describing the contents of the archive.
- `model/`: A directory containing zero or more `compas_model` JSON files.
- `nesting/`: A directory containing zero or more nesting result JSON files.
- `blueprints/` : A directory containing zero or more blueprints for this cog.

**Manifest Schema:**
```json
{
  "items": [
    {
      "model": "model_filename.json",
      "nesting": "nesting_filename.json"
    }
  ]
}
```

### Agent Communication Protocol

Agents communicate with the orchestrator via 6 types of messages sent over MQTT. The schema for these protocol messages are defined using Protocol Buffers (`protobuf`) and the `compas_pb` library for type-safe serialization of COMPAS objects:

1. **Task Assignment**: The orchestrator sends a `TaskAssignmentMessage` when a task is ready to be executed.
2. **Task Claim Request**: Agents capable of executing the task send a `TaskClaimRequest` to the orchestrator.
3. **Task Allocation**: The orchestrator selects one agent and sends a `TaskAllocationMessage` confirming the assignment.
4. **Task Status Updates**: When the allocated agent begins executing a task it publishes a `TaskStatusUpdateMessage` so the orchestrator know the task is now actively running. After this, the agent may send additional status updates (e.g., progress reports) as needed.
5. **Task Completion**: The agent sends a `TaskCompletionMessage` with the task result upon completion (success or failure).
6. **Task Completion ACK**: The orchestrator sends a `TaskCompletionAckMessage` immediately after it accepts a `TaskCompletionMessage`.

### Execution Modes

The system supports different execution modes for tasks:

* **EXCLUSIVE** (Default): Standard "first-come-first-serve" model. The orchestrator assigns the task to the first agent that claims it. Subsequent claims are ignored (ie. rejected).
* **COMPETITIVE**: The task is assigned to *all* agents that claim it.
  * The orchestrator sends a `TaskAllocationMessage` to every agent that claims the task.
  * Agents execute the task in parallel.
  * The first agent to complete the task sends a `TaskCompletionMessage`.
  * The orchestrator accepts this completion, updates the task state to `SUCCEEDED`, and broadcasts a `TaskCompletionAckMessage` identifying the "winner" (accepted agent).
  * Other agents running the task receive the ACK. If they are not the winner, they must **cancel** their local execution immediately, without sending a `TaskCompletionMessage`.

### Re-dispatch (Unclaimed Task Watchdog)

If a dispatched task (`TaskAssignmentMessage`, state `READY`) receives no `TaskClaimRequest` within a backoff window, the orchestrator's `RedispatchPoller` (`src/antikythera_orchestrator/orchestrator.py`) re-publishes the same `TaskAssignmentMessage`. This only guards against *unclaimed* tasks — it does not handle agent crashes mid-execution, timeouts after claim, or rejected claims.

- A background thread polls tracked tasks every second; a task is tracked from dispatch until claimed (`RUNNING`) or reset.
- Backoff is exponential: `min(base_delay * 2**attempts, max_delay)` between re-publishes.
- After `max_redispatches` unclaimed attempts, the poller synthesizes a `TaskCompletionMessage(state=FAILED, error.code="NO_AGENT_CLAIMED")`, failing the task (and session) as if the agent had reported failure.
- Config knobs (`antikythera/config.py`): `REDISPATCH_BASE_DELAY` (default 2s), `REDISPATCH_MAX_DELAY` (default 90s), `MAX_REDISPATCHES` (default 5).
- Orthogonal to `ExecutionMode`: tracking always starts at `READY` regardless of EXCLUSIVE/COMPETITIVE.

**Protocol Buffer Definitions**

The complete protobuf schema is maintained in [`src/antikythera/proto/antikythera.proto`](src/antikythera/proto/antikythera.proto).

**Key message types:**
- `TaskAssignmentMessage`: Sent by orchestrator to agents when tasks are ready
- `TaskClaimRequest`: Sent by agents to claim a task
- `TaskAllocationMessage`: Sent by orchestrator to confirm task assignment to a specific agent
- `TaskStatusUpdateMessage`: Sent by agents as soon as they start working on a task
- `TaskCompletionMessage`: Sent by agents to orchestrator upon task completion
- `TaskCompletionAckMessage`: Sent by orchestrator after recording task completion to signal that the task is closed for all agents
- `TaskState`: Enum defining task lifecycle states
- `TaskError`: Error information for failed tasks
- `ExecutionMode`: Enum defining execution mode (EXCLUSIVE, COMPETITIVE)

**Message structure overview:**
```protobuf
// Canonical definitions in src/antikythera/proto/antikythera.proto
package antikythera.v1;

enum ExecutionMode {
  EXECUTION_MODE_EXCLUSIVE = 0;   // Default: Only one agent is allocated the task
  EXECUTION_MODE_COMPETITIVE = 1; // Multiple agents can run, first to finish wins
}

message TaskAssignmentMessage {
  string id = 1;                                    // Required: unique task identifier
  string type = 2;                                  // Required: task type (determines which agent handles it)
  map<string, compas_pb.data.AnyData> inputs = 3;   // Optional: task inputs from blueprint session data
  repeated string output_keys = 4;                  // Optional: expected output keys (for validation)
  map<string, compas_pb.data.AnyData> params = 5;   // Optional: task-specific parameters (not from session data)
  google.protobuf.Timestamp timestamp = 6;          // Optional: assignment timestamp
  ExecutionMode execution_mode = 7;                 // Optional: execution mode
}

message TaskClaimRequest {
  string task_id = 1;                               // Required: task identifier
  string agent_id = 2;                              // Required: agent identifier
  google.protobuf.Timestamp timestamp = 3;          // Optional: claim timestamp
}

message TaskAllocationMessage {
  string task_id = 1;                               // Required: task identifier
  string assigned_agent_id = 2;                     // Required: agent identifier allocated to the task
  google.protobuf.Timestamp timestamp = 3;          // Optional: allocation timestamp
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

A domain-specific language (DSL) implemented in Python provides an ergonomic interface for defining blueprints programmatically. This enables:

- **Fluid Task Dependencies**: Use the right-shift operator (`>>`) to define dependencies clearly and concisely.
- **Type checking**: Validation during development.
- **Reuse**: Easy reuse of process components and patterns.
- **Integration**: Seamless integration with existing Python-based workflows.

**Example:**

```python
from antikythera.models import Task, Blueprint

# Define tasks
t_start = Task(id="start", type="system.start")
A = Task(id="A", type="agent.task")
B = Task(id="B", type="agent.task")
C = Task(id="C", type="agent.task")
t_end = Task(id="end", type="system.end")

# Define flow using the >> operator
# Start -> A and B run in parallel -> C waits for both -> End
t_start >> [A, B] >> C >> t_end

bp = Blueprint(id="example", tasks=[t_start, A, B, C, t_end])
```

### Phase 3: LLM-Assisted Authoring (Long-term Vision)

In the ideal long-term vision, an LLM-based frontend will enable definition of blueprints in natural language. This system will:

1. Accept natural language descriptions of blueprints
2. Incorporate structured data inputs:
   - COMPAS Model of the fabricatable object
   - Model(s) of fabrication environments (e.g., a `RobotCell` for robotic fabrication)
3. Generate a formal **Blueprint** definition
4. Support iterative refinement through natural language interaction

The expansion from prototypical blueprints to more deterministic or algorithmic results will be handled by MCP tools, maintaining a separation between high-level blueprint definition and low-level execution details.

### Proof-of-Concept: Grasshopper components

A set of Grasshopper components could be developed to allow visual programming of blueprints. This would serve as a good blueprint-prototyping alternative to the JSON format, especially for users familiar with visual programming paradigms.

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
- **CHANGELOG.md**: contains only changes affecting public API, entries regarding internal changes should reflect their effect on the users.


### Repository Structure

The Antikythera project is organized as follows:

- **`antikythera/`**: Core package containing data models and schemas
  - **`models/`**: Data models and schemas

- **`antikythera_orchestrator/`**: Main orchestration engine components and API
  - **`orchestrator/`**: Orchestrator implementation
  - **`storage/`**: Persistence layer
  - **`sequencers.py`**: Logic for dynamic blueprint expansion
  - **`system_agents.py`**: Built-in system agents (start, end, sleep, composite)
  - **`api.py`**: FastAPI application implementation
  - **`__main__.py`**: Application entry point

- **`antikythera_agents/`**: Built-in agent implementations
  - **`launcher.py`**: Agent launcher
  - **`reference_agent.py`**: Worked example agent — see "Reference Agent" below

### Extension Points

Antikythera is designed to be extensible. Custom agents can be implemented in separate repositories and languages, provided they adhere to the **Agent Communication Protocol**. The system supports:

- Python-based agents using the provided base classes and `compas_pb` serialization
- External agents communicating via MQTT using the defined protobuf message schemas

### Agent Execution Context & Lifecycle

To support competitive execution (and advanced execution patterns like cancellation, pausing, or progress reporting), agents need to interact with the runtime environment during task execution. This is achieved via a `ExecutionContext` object passed to the tool.

**Python Agent Implementation Pattern:**

1.  **Launcher/Runtime**: Creates a `ExecutionContext` for each execution. This context wraps thread-safe primitives (like `threading.Event` or `asyncio.Future`) for signalling.
2.  **Base Agent**: Injects the `context` object into the tool function if the signature requests it.
3.  **Tool Implementation**: Accepts `context` as an argument to check for cancellation or register cleanup hooks.

```python
@tool(name="long_process")
def run_long_process(self, task: Task, context: ExecutionContext) -> dict:
    # Polling usage
    for i in range(100):
        if context.is_cancelled:
            print("Job cancelled!")
            return None 

        time.sleep(1)

    # Callback usage
    def cleanup():
        print("Cleaning up resources...")

    context.on_cancel(cleanup)
    
    return {"result": "done"}
```

### Expansion Context

Tools inside a dynamically expanded inner blueprint often need to know which item they are
working on — the `element_id`, and whatever else the `Sequencer` attached. This is the
**expansion context**, distinct from `ExecutionContext` above: it is data about the task's
place in the dynamic expansion, not a lifecycle handle.

The expansion context already flows end to end without any tool-level plumbing: the
orchestrator stores it per inner blueprint, packs it into the task assignment message, the
protocol carries it, and the launcher lands it on `task.context`. A tool declares which keys
it needs by annotating a parameter `Context[T]`; binding is a lookup by name in that dict.

```python
@tool(name="process")
def process_element(self, element_id: Context[str]) -> dict:
    return {"element_id": element_id}
```

A `Context[T]` parameter for a key absent from `task.context` raises `ToolBindingError` (see
`ADR-0002`), naming the key, before the tool body runs. `Context[T]` and `ExecutionContext`
parameters may coexist on the same signature. The catalog reports a tool's `Context[T]`
parameters under `requires_context` — a list of names, since the value comes from the runtime
rather than from anything a blueprint author writes.

### Reference Agent

`antikythera_agents/reference_agent.py` (`ReferenceAgent`, agent type `reference`) is the
worked example for the tool convention above — copy from it when authoring a new agent.
Between its three tools (`assemble`, `wait`, `passthrough`) it exercises every annotation
kind the binder understands: a plain task input and one declared explicitly with `Input[T]`,
a required and a defaulted `Param[T]`, a `Context[T]` value, an `Optional[T]` input, a
`TypedDict` return with both a required and a `NotRequired` key, the `Task` escape hatch, and
`ExecutionContext` cancellation. It has no dependency beyond this package, so it runs in CI.
`examples/reference_agent_demo.json` drives it end to end through a real orchestrator run.

## Roadmap

- **M1 (Toy problem 1):** author a trivial blueprint composed by 3 tasks (A1, A2, B1) + 1 start and 1 end task. A1 and A2 depend on START, B1 depends on A1 and A2, END depends on B1. A1 will wait for user input on the terminal (or any other input method) and define one output data key. A2 will be a "sleep 5 seconds" task, B1 will define a data input on the output key generated by A1 and print it.
- **M2 (Toy problem 2):**: author a blueprint for robotic pick and place of a single element using a 6-DoF robot (ABB GoFa robot model) composed by 7 tasks: A1: plan trajectory, A2: move/execute trajectory, A3: actuate gripper, A4: plan trajectory, A5: move/execute trajectory. All tasks are sequential and depend on the previous one. START and END are placed at the start and end of the blueprint respectively. The `move/execute trajectory` tasks should implement `needs_approval`. This means, there are 3 new agent types: `compas_fab.plan_trajectory` (used to calculate approach and retract trajectories), `compas_rrc.move_to_trajectory` and `compas_rrc.actuate_gripper`.
- **M4 (Toy problem 4):**: Inner blueprints using `system.composite` (static): 1) Implement static inner blueprint and agent, 2) Inputs and Outputs of inner blueprints.
- **M5 (Toy problem 5):** Pick and place for a single element using a 6-DoF robot with inner blueprints. Tasks: 1) `Plan Pick` and `Plan Place` for `MoveIt` planner agent. 2) For next Milestote: Model is read-only and globally accessible inside inner blueprints, but the element sequencer will assign additional information: current element id + list of state (built/not built) of all elements.
- **M6 (Toy problem 6):**: Add `compas_model` to M5, including element ids referenced from tasks and dynamic inner blueprint expansion based on calls to some kind of sequencer (sequencing the model's elements).
- **M8 (Toy problem 8):**: Implement conditional logical execution of tasks based on input data and/or parameters.

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


## TODOs (for us humans! go away "CLAUDE"!)

- [ ] Prepare Hello World of Antikythera: simple, yet impressive for demo'ing
  - [ ] Demonstrates the distributed nature of the system:
    - [ ] Showcase dynamic task re-assignment by having two robots running a cell, and making one fail, so that all subsequent tasks are automatically re-assigned to the other robot (depends on retry policies).
    - [ ] Human-in-the-loop: human selects the next element to fabricate (using a phone agent)
    - [ ] Make each host visibly acting whenever a task is executed in it (e.g. light up a LED)
  - [ ] No-Code fabrication process
    - [ ] Host 0: Orchestrator: Raspberry Pi
    - [ ] Host 1: Raspberry Pi
      - [ ] Scene Agent (robot agnostic, RobotCell + RobotCellState support via compas_fab)
      - [ ] Planning Agent: FK+IK+LM (Cartesian Motion)+FM (Free space motion) -> Consider how to make these MATERIAL or ELEMENT-CENTRIC or WORKOBJECT-CENTRIC
    - [ ] Host 2: Raspberry Pi
      - [ ] RRC Agent: execution for ABB (Move To Frame + Move to Config + Move to Trajectory + Set IO + Get IO)
    - [ ] Host 3: Grasshopper
      - [ ] GH Agent receives trajectories over task input, waits for user approval then sends task completion
    - [ ] Host 4: Phone -> Human-in-the-loop agent to fabricate some elements manually
- [ ] Add retry policies and idempotency definition for tasks and blueprints, e.g. in a composite blueprint, the execute robotic motion task can fail and that could trigger a retry of the whole inner blueprint (or just the failed task, depending on the case)
  - [ ] Consider how or if this includes or provides backtracking capabilities
- [ ] Create an AGENT CATALOG
  - [ ] We don't create our own Registry of agents, instead, we create a meta search aggregator to search over Pypi+Docker Hub+GHCR for python package and/or containers. This way we don't need to maintain a registry of agents, but we can still have a discoverability layer for users to find existing agents.
  - [ ] Agent catalog is the result of the aggregation of registry results
- [ ] Benchmark latency of ImmuDB and/or network communication
- [ ] AKT Yaml host file (`akt.yaml`) for defining what agents to launch on a specific machine and how to connect to broker
  - [ ] Support launching agents in containers
  - [ ] Support launching Python agents (via `uv run python` command in the same venv as `akt`)
  - Sample `akt.yaml`:
  ```yaml
  broker: 192.168.0.100

  agents:
    fab:
      image: antikythera/compas_fab/agents
      env:
        - CNC_IP_ADDRESS=192.168.0.101
    rrc:
      image: antikythera/compas_rrc/agents
    demo:
      python: git+https://github.com/gramaziokohler/some_pip_package.git
        --> uv pip install git+https://github.com/gramaziokohler/some_pip_package.git
            uv run python -m antikythera_agents run
  ```

- [ ] BT: Explore if we can/should use BTs for control logic (BT inside a blueprint | Blueprint inside a BT)
- [ ] Authoring tools:
  - [ ] Graphical interface
  - [ ] LLM-assisted authoring
  - [ ] Text-editor to make changes to the JSON directly
  - [ ] Download blueprints: back to the JSON representation
  - [ ] Reorder tasks in paused blueprint (re-order only in same blueprint level, only non-finished tasks)
- [ ] Naming sessions
- [ ] Fully expanded blueprint in the Session Monitor (instead of jumping between inner blueprints)
  - [ ] Collapse-all/Expand-all buttons
  - [ ] Inner blueprints should be visually distinguishable (maybe a dotted border?)
- [ ] Test static inner blueprints (especially twice expanded in the same blueprint, as seen in the CNC control blueprints)
- [ ] Model and current element visualization in the Session Monitor
- [ ] Unify representations of Task across the system. We have 16 according to the LLM, but some are more relevant than others:
  - [ ] class Task: This should be the one true representation of Task.
  - [ ] Task in the TaskAssignmentMessage (protobuf message) [Currently half-assed]
  - [ ] GraphNode (is it used?) in the frontend / ReactFlow Node?
- [ ] Some kind of distributed file system
- [ ] Observability
  - [ ] Add MQTT log listener on the orchestrator and log agent entries (consider logging to DB?)
- [ ] Conceptualize map/reducer strategy for output data management in dynamic tasks. 
- [ ] Implement a XR interface and XR agents
- [ ] Grasshopper components to control execution
- [ ] Grasshopper Agents (GHaaS): two components at least, one to receive a task assignment, and one to output task completion, in between, any GH component can be used.
- [ ] Grasshopper could become a full fledged interface for antikythera -> Define how.

- Protocol robustness
  - [ ] explore Jespen for testing and verification
  - [ ] explore erlang principles 

