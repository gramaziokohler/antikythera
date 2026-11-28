"""Running a blueprint in one process with the top-level API and context managers."""

import pytest

import antikythera as akt
from antikythera import Blueprint
from antikythera import Task
from antikythera import TaskInput
from antikythera import TaskOutput
from antikythera import tool


@tool("local_run.label")
def label(item: str, suffix: str) -> dict:
    return {"label": f"{item}-{suffix}"}


def _blueprint() -> Blueprint:
    start = Task(id="start", type="system.start")
    task = Task(
        id="label",
        type="local_run.label",
        # `suffix` is read from "missing_key", which nothing writes: its value is the default.
        inputs=[TaskInput(name="item", value="beam"), TaskInput(name="suffix", get_from="missing_key", value="A")],
        outputs=[TaskOutput(name="label")],
    )
    end = Task(id="end", type="system.end")
    start >> task >> end
    return Blueprint(id="local-run", name="Local run", tasks=[start, task, end])


def test_from_blueprint_with_context_managers():
    transport, storage = akt.InMemoryTransport(), akt.InMemoryStorage()

    with akt.ActorLauncher(transport=transport, actor_types=["system", "local_run"], discover=False):
        with akt.Orchestrator.from_blueprint(_blueprint(), transport=transport, storage=storage) as orchestrator:
            assert orchestrator.await_completion(timeout=10)

    assert orchestrator.state == "completed"
    assert orchestrator.session.bsid.startswith("local-run-")
    assert orchestrator.load_outputs()["label"] == "beam-A"


def test_blueprint_block_with_output_links():
    transport, storage = akt.InMemoryTransport(), akt.InMemoryStorage()
    with Blueprint("linked") as blueprint:
        first = Task("first", "local_run.label", inputs={"item": "beam", "suffix": "A"})
        second = Task("second", "local_run.label", inputs={"item": first.output("label"), "suffix": "B"})
        result = second.output("label")

    with akt.ActorLauncher(transport=transport, actor_types=["system", "local_run"], discover=False):
        with akt.Orchestrator.from_blueprint(blueprint, transport=transport, storage=storage) as orchestrator:
            assert orchestrator.await_completion(timeout=10)

    outputs = orchestrator.load_outputs()
    assert outputs[first.output("label")] == "beam-A"
    assert outputs[result] == "beam-A-B"


def test_broker_arguments_are_deprecated(monkeypatch):
    transport = akt.InMemoryTransport()
    monkeypatch.setattr("antikythera_orchestrator.orchestrator._get_eve_transport", lambda **kwargs: transport)
    monkeypatch.setattr("antikythera_actors.launcher._get_eve_transport", lambda **kwargs: transport)

    with pytest.warns(DeprecationWarning, match="MqttTransport"):
        akt.Orchestrator(akt.BlueprintSession(bsid="deprecated", blueprint=_blueprint()), broker_host="localhost", storage=akt.InMemoryStorage())
    with pytest.warns(DeprecationWarning, match="broker_port, tls"):
        akt.ActorLauncher(broker_port=1883, tls=True, discover=False, actor_types=["local_run"])


def test_top_level_names_resolve():
    from antikythera_actors import Param
    from antikythera_orchestrator import Orchestrator

    assert akt.Param is Param
    assert akt.Orchestrator is Orchestrator
    assert "Blueprint" in dir(akt)
