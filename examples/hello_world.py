from compas_eve.codecs import ProtobufMessageCodec
from compas_eve.memory import InMemoryTransport

from antikythera.models import Blueprint, BlueprintSession, Task, TaskInput, TaskOutput
from antikythera_actors import Actor, ActorLauncher, actor, tool
from antikythera_orchestrator import InMemoryStorage, Orchestrator


# An actor does the work. Each of its tools is one job it can do.
@actor(type="greeter")
class Greeter(Actor):
    @tool(name="hello")
    def hello(self, name: str) -> dict:
        return {"greeting": f"Hello, {name}!"}


# A blueprint lists the tasks to do, and their order.
start = Task(id="start", type="system.start")
hello = Task(
    id="hello",
    type="greeter.hello",  # run by the "hello" tool of the "greeter" actor
    inputs=[TaskInput(name="name", value="world")],
    outputs=[TaskOutput(name="greeting")],
)
end = Task(id="end", type="system.end")
start >> hello >> end
tasks = [start, hello, end]
blueprint = Blueprint(id="hello-world", name="Hello, world", tasks=tasks)

# Run it all in this Python process: no message broker, no database.
transport = InMemoryTransport(codec=ProtobufMessageCodec())
storage = InMemoryStorage()

actors = ActorLauncher(transport=transport)
actors.start()

session = BlueprintSession(bsid="hello-1", blueprint=blueprint)
orchestrator = Orchestrator(session, transport=transport, storage=storage)
orchestrator.start()
orchestrator.await_completion(timeout=10)
actors.stop()

with storage.session_storage("hello-1") as data:
    print(data.get("hello-world", "greeting"))  # Hello, world!
