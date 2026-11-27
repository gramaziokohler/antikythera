"""Running a blueprint in one process with the top-level API and context managers."""

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
    with storage.session_storage(orchestrator.session.bsid) as data:
        assert data.get("local-run", "label") == "beam-A"


def test_top_level_names_resolve():
    from antikythera_actors import Param
    from antikythera_orchestrator import Orchestrator

    assert akt.Param is Param
    assert akt.Orchestrator is Orchestrator
    assert "Blueprint" in dir(akt)
