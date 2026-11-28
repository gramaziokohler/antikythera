from antikythera import (
    ActorLauncher,
    Blueprint,
    InMemoryStorage,
    InMemoryTransport,
    Orchestrator,
    Task,
    tool,
)


# A tool is one job an actor can do. This one is the "hello" tool of the "greeter" actor.
@tool("greeter.hello")
def hello(name: str) -> dict:
    return {"greeting": f"Hello, {name}!"}


# A blueprint lists the tasks to do, and their order.
with Blueprint("hello-world") as blueprint:
    Task("greet", "greeter.hello", inputs={"name": "world"}, outputs=["greeting"])

# Run it all in this Python process: no message broker, no database.
transport = InMemoryTransport()
storage = InMemoryStorage()

with ActorLauncher(transport=transport):
    with Orchestrator.from_blueprint(blueprint, transport=transport, storage=storage) as orchestrator:
        orchestrator.await_completion(timeout=10)

print(orchestrator.load_outputs()["greeting"])  # Hello, world!
