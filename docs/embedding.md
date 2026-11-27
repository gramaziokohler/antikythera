# Embedding the orchestrator

The orchestrator does not need the HTTP API, Redis or an MQTT broker. It is a Python class
that takes a blueprint session, a transport to reach actors over, and a storage backend.
That makes Antikythera usable as a small process coordinator inside any Python application.

## In a single process

With an in-memory transport and in-memory storage, the orchestrator and the actors run in
the same process and nothing else is needed:

```python
from compas_eve.codecs import ProtobufMessageCodec
from compas_eve.memory import InMemoryTransport

from antikythera.models import Blueprint, BlueprintSession, Task, TaskInput, TaskOutput
from antikythera_actors import Actor, ActorLauncher, actor, tool
from antikythera_orchestrator import InMemoryStorage, Orchestrator


@actor(type="math")
class MathActor(Actor):
    @tool(name="double")
    def double(self, value: int) -> dict:
        return {"result": value * 2}


start = Task(id="start", type="system.start")
double = Task(id="double", type="math.double", inputs=[TaskInput(name="value", value=21)], outputs=[TaskOutput(name="result")])
end = Task(id="end", type="system.end")
start >> double >> end
blueprint = Blueprint(id="answer", name="Answer", tasks=[start, double, end])

transport = InMemoryTransport(codec=ProtobufMessageCodec())
storage = InMemoryStorage()

actors = ActorLauncher(transport=transport)
actors.start()

orchestrator = Orchestrator(BlueprintSession(bsid="answer-1", blueprint=blueprint), transport=transport, storage=storage)
orchestrator.start()
orchestrator.await_completion(timeout=10)

print(storage.session_storage("answer-1").get("answer", "result"))  # 42
actors.stop()
```

The transport must use `ProtobufMessageCodec`, the format the orchestrator and actors
exchange. Both constructors reject a transport that does not.

## Across machines

Keep the storage in memory but talk MQTT, and actors can run anywhere that reaches the
broker, for example started with `uvx` as described in [Running actors](actors.md):

```python
orchestrator = Orchestrator(session, broker_host="mqtt.example.org", storage=InMemoryStorage())
```

Any other `compas_eve` transport works the same way. Zenoh, for instance, needs no broker at all.

## Storage

`InMemoryStorage` holds sessions, blueprints and models for as long as the process runs.
Put the blueprints that composite tasks refer to, and the models that sequencers read, into
it before starting:

```python
with storage.blueprint_storage() as blueprints:
    blueprints.add_blueprint(inner_blueprint)

with storage.model_storage() as models:
    models.add_model("my-model", model)
```

`RedisStorage` is the default backend and keeps everything across restarts; it is what the
HTTP API service uses. Implement `StorageBackend` to keep state somewhere else.
