# Software architecture

> **Summary**: Antikythera is an distributed system for orchestration of fabrication processes in the context of architecture and construction.

---

## Terminology

* `agent`: an entity that can run a specific type of `task`. It can be a remote machine or a local process. Examples of agents are an OS-level process, a robot control program, a CNC program, a microcontroller program, etc.
* `task` is a unit of work that can be executed by an `agent` . They are `nodes` in the `graph` that describes the entire `fabrication process`. A `task` is effectivelly a tiny state machine that can be in one of the following states: `not started`, `running`, `succeeded`, `failed`. It declaratively defines input and output data so that data dependencies can be defined between nodes.
* `graph`, aka `DAG`: a directed acyclic graph that describes the entire `fabrication process`. It is composed by `nodes` (tasks) and `edges` (dependencies). It will always contain at least two nodes: `START` and `END`, which can also define data dependencies to enable composing graphs into larger graphs.
* `fabrication process`: the highest level of abstraction in Antikythera, describes all the steps to fabricate a physical object, for example, in a timber assembly, it describes the step-by-step assembly of each of the timber beams and how they depend on each other. It is internally represented as a `graph`. It has a JSON representation, the specific format still needs to be defined.
* `behavior tree`: a robotics-oriented representation of a decision tree that can be used to implement control logic for semi-autonomous robot operation.
* `FPID`: a fabrication process identifier, a UUID that uniquely identifies a fabrication process session. A single session can have very long running times, easily reaching into multi-weeks.

## Technology

* Python 3.12
* `MQTT` based on `compas_eve` for the transport layer of the event system.
* `compas` for the core framework, including the `DAG` implementation.
* `compas_model` for model representation (i.e. the fabricatable object).
* `immudb` for data storage.

Tentative technologies:

* `compas_fab` for `tasks` of type **Robotic Planning**. At the time of writing, it will use Project Theseus, i.e. the `wip_process` branch.
* `compas_emma` for `tasks` of type **Behavior Tree**.
* `compas_rrc` as the execution backend for `compas_emma` behavior trees.
* `FastMCP` if we implement `tasks` of type **MCP Server/tools**.

---

## High-Level Architecture

- **Orchestrator**: control-plane
- **Agents:** execution-plane
- **Data store:** data-plane
- **Observability:** TDB

---

## Components

### Orchestrator

The **orchestrator** is in charge of coordinating the execution of a process described as a **directed acyclic graph** (DAG). The DAG is composed by **tasks** in the nodes, and their dependencies in the edges. An task has a state (not started, running, succeeded, failed), it declaratively defines input and output data so that data dependencies can be defined between nodes.

Each task is executed by an **agent**, either remote or local. The overall system has location transparency, so agents can be running in one or more machines in the same or different networks.

The orchestrator runs a single **fabrication process** at a time. Each run of a fabrication process is identified by a session identifier (`FPID`). Parallelism can be achieved inside the process itself by using different agents. 

The orchestrator loads a **fabrication process** from a file or an API call, and will begin to execute it. The link between the JSON representation and the in-memory execution should not be lost during loading, because it is necessary to allow live modifications of the running graph. Modifications of the graph are append-only operations, so that the orchestrator can always keep track of the original graph. Edge-cases like the deletion of a node should be handled with care, to gracefully deal with loss of data dependency as well as case of a agent running a node while it is deleted.

### Agents

An **agent** is an entity that can run a specific type of **task**.

Initially, only very simple agents will be implemented to execute toy problems.

### Data store

The system uses a persistent data store to keep track of state. The data store is used to store the state of the **orchestrator** itself, and the state of the **fabrication process**.

The data store contains two types of data, internal and external:
* Orchestrator data, considered internal.
* Fabrication process data, considered external and linked to a specific `FPID` (fabrication process session identifier).

The global nature of fabrication process data is mitigated by the data dependencies defined in the **DAG**, i.e. by defining input and output data keys declaratively.

### Observability

TBD

---

## File formats

### Fabrication process

```json

TBD
```

---

## Authoring Surface

In the ideal, long-term vision of the project, an LLM-based frontend would receive a natural-language description of a fabrication process and the corresponding data: 1) COMPAS Model of the fabricatable object, and 2) A model of the fabrication environments (e.g. a `RobotCell` for the case of robotic fabrication). The LLM would then generate a **fabrication process** in the form the text format defined above, and that would be loaded/compiled/transformed into different internal representations as needed. The expansion from a prototypical process to mode deterministic or algorithmic results would be off-loaded to MCP tools.

However, in the short-term, we will use only the simple JSON-based representation as the authoring surface.

Eventually, a small DSL-ish Python API would be integrated.

---

## Roadmap

- **M1 (Toy problem 1):** author a trivial process composed by 3 tasks (A1, A2, B1) + 1 start and 1 end task. A1 and A2 depend on START, B1 depends on A1 and A2, END depends on B1. A1 will wait for user input on the terminal (or any other input method) and define one output data key. A2 will be a "sleep 5 seconds" task, B1 will define a data input on the output key generated by A1 and print it.
- **M2**: TBD
- **M3**: TBD

