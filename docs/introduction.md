# Introduction

Antikythera is a distributed process manager for robotic fabrication and automation workflows.
It provides a blueprint-driven execution model where tasks are orchestrated across multiple agents.

## Core Concepts

**Blueprints** define the structure of a session: the tasks to run, their dependencies, and
the agents responsible for executing them.

**Agents** are processes that subscribe to tasks and report results back to the orchestrator.

**The Orchestrator** is the central coordinator. It receives a blueprint, schedules tasks,
and tracks session state.
