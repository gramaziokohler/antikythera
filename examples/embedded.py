"""Antikythera as a process coordinator inside a Python program.

The orchestrator, the built-in system actor and a custom actor all run in this process:
no MQTT broker, no Redis, no web service. Run it with:

    python examples/embedded.py
"""

from compas_eve.codecs import ProtobufMessageCodec
from compas_eve.memory import InMemoryTransport

from antikythera.models import Blueprint
from antikythera.models import BlueprintSession
from antikythera.models import Task
from antikythera.models import TaskInput
from antikythera.models import TaskOutput
from antikythera_actors import Actor
from antikythera_actors import ActorLauncher
from antikythera_actors import actor
from antikythera_actors import tool
from antikythera_orchestrator import InMemoryStorage
from antikythera_orchestrator import Orchestrator


@actor(type="math")
class MathActor(Actor):
    @tool(name="double")
    def double(self, value: int) -> dict:
        return {"result": value * 2}

    @tool(name="add")
    def add(self, a: int, b: int) -> dict:
        return {"sum": a + b}


def build_blueprint() -> Blueprint:
    # Two doublings run in parallel, then their results are added.
    start = Task(id="start", type="system.start")
    left = Task(id="left", type="math.double", inputs=[TaskInput(name="value", value=10)], outputs=[TaskOutput(name="result", set_to="left")])
    right = Task(id="right", type="math.double", inputs=[TaskInput(name="value", value=11)], outputs=[TaskOutput(name="result", set_to="right")])
    add = Task(
        id="add",
        type="math.add",
        inputs=[TaskInput(name="a", get_from="left"), TaskInput(name="b", get_from="right")],
        outputs=[TaskOutput(name="sum")],
    )
    end = Task(id="end", type="system.end")
    start >> [left, right] >> add >> end
    return Blueprint(id="answer", name="The answer", tasks=[start, left, right, add, end])


def main() -> int:
    transport = InMemoryTransport(codec=ProtobufMessageCodec())
    storage = InMemoryStorage()

    actors = ActorLauncher(transport=transport)
    actors.start()
    try:
        orchestrator = Orchestrator(BlueprintSession(bsid="answer-1", blueprint=build_blueprint()), transport=transport, storage=storage)
        orchestrator.start()
        orchestrator.await_completion(timeout=30)
    finally:
        actors.stop()

    with storage.session_storage("answer-1") as session:
        answer = session.get("answer", "sum")
    print(f"The answer is {answer}")
    return answer


if __name__ == "__main__":
    main()
