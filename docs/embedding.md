# Embedding the orchestrator

The orchestrator is a Python class. It does not need the HTTP service, Redis or an MQTT
broker, so you can use Antikythera to coordinate tasks inside any Python program.

## The parts

An orchestrator needs three things:

- a **session**: the blueprint to run, and an id for this run.
- a **transport**: how to reach the actors.
- a **storage**: where to keep the session and its data.

The [hello world](index.md#hello-world) runs everything in one process, with an in-memory
transport and an in-memory storage:

```python
from antikythera import ActorLauncher, InMemoryStorage, InMemoryTransport, Orchestrator

transport = InMemoryTransport()
storage = InMemoryStorage()

with ActorLauncher(transport=transport):
    with Orchestrator.from_blueprint(blueprint, transport=transport, storage=storage) as orchestrator:
        orchestrator.await_completion(timeout=10)
```

`ActorLauncher` starts the actors defined in your program and the ones installed as
plugins, including the `system` actor that runs the start and end tasks.
`Orchestrator.from_blueprint` creates a new session of the blueprint, with a random id.
Each `with` block starts its part when it begins, and stops it when it ends.
`await_completion` waits until the session has finished, and returns `False` if the time
ran out first.

Without the `with` blocks, call `start()` and `stop()` yourself. To choose the session id,
or to resume a session, create the `BlueprintSession` and pass it to `Orchestrator`.

The transport must use `ProtobufMessageCodec`, because that is the message format of the
orchestrator and the actors. Both refuse a transport with another codec.
`antikythera.InMemoryTransport` uses it already; the other transports take it as `codec=`.

## Actors on other machines

To let actors on other machines take part, use a network transport instead. With MQTT,
pass the broker address:

```python
orchestrator = Orchestrator(session, broker_host="mqtt.example.org", storage=InMemoryStorage())
```

The actors then connect to the same broker, for example with `uvx` as described in
[Writing actors](actors.md#running-actors). [NATS](nats.md) and [Zenoh](zenoh.md) work as
well, and any other `compas_eve` transport can be passed as `transport=`.

## Storage

`InMemoryStorage` keeps sessions, blueprints and models until the program ends. If a
blueprint has composite tasks, or reads a model, add the inner blueprints and the models
to the storage before you start:

```python
with storage.blueprint_storage() as blueprints:
    blueprints.add_blueprint(inner_blueprint)

with storage.model_storage() as models:
    models.add_model("my-model", model)
```

To read the results, open the session data. Values are stored per blueprint id:

```python
with storage.session_storage(orchestrator.session.bsid) as data:
    print(data.get("hello-world", "greeting"))
```

`RedisStorage` keeps everything when the program restarts. It is the default, and what the
HTTP service uses. To keep data somewhere else, implement
[StorageBackend][antikythera_orchestrator.storage.backends.StorageBackend].
