# API reference

Antikythera is three Python packages, installed together as `antikythera-sdk`:

| Package | For |
| --- | --- |
| `antikythera` | Blueprints and tasks, reading and writing them, and the transports |
| `antikythera_actors` | Writing and running actors |
| `antikythera_orchestrator` | Running blueprints: the orchestrator, its HTTP API and its storage |

Most programs only need a few names:

| Name | Page |
| --- | --- |
| `Blueprint`, `Task`, `TaskInput`, `TaskOutput`, `BlueprintSession` | [Blueprints](blueprints.md) |
| `Actor`, `actor`, `tool`, `Param`, `run` | [Actors](actors.md) |
| `Orchestrator` | [Orchestrator](orchestrator.md) |
| `InMemoryStorage`, `RedisStorage` | [Storage](storage.md) |
