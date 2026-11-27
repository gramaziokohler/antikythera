from antikythera import (
    ActorLauncher,
    Blueprint,
    InMemoryStorage,
    InMemoryTransport,
    Orchestrator,
    Task,
    TaskInput,
    TaskOutput,
    tool,
)


# A tool is one job an actor can do. This one is the "hello" tool of the "greeter" actor.
@tool("greeter.hello")
def hello(name: str) -> dict:
    return {"greeting": f"Hello, {name}!"}


# A blueprint lists the tasks to do, and their order.
start = Task(id="start", type="system.start")
greet = Task(
    id="greet",
    type="greeter.hello",
    inputs=[TaskInput(name="name", value="world")],
    outputs=[TaskOutput(name="greeting")],
)
end = Task(id="end", type="system.end")
start >> greet >> end
blueprint = Blueprint(id="hello-world", name="Hello, world", tasks=[start, greet, end])

# Run it all in this Python process: no message broker, no database.
transport = InMemoryTransport()
storage = InMemoryStorage()

with ActorLauncher(transport=transport):
    with Orchestrator.from_blueprint(blueprint, transport=transport, storage=storage) as orchestrator:
        orchestrator.await_completion(timeout=10)

with storage.session_storage(orchestrator.session.bsid) as data:
    print(data.get("hello-world", "greeting"))  # Hello, world!
