"""Tools written as plain functions: `@tool("<actor_type>.<tool>")`."""

import textwrap

import pytest

import antikythera_actors.serve as serve_module
from antikythera.models import Task
from antikythera.models import TaskInput
from antikythera.models import TaskParam
from antikythera.transports.memory import InMemoryTransport
from antikythera_actors import Actor
from antikythera_actors import Param
from antikythera_actors import actor
from antikythera_actors import cli
from antikythera_actors import get_actor_class
from antikythera_actors import run
from antikythera_actors import tool
from antikythera_actors.launcher import ActorLauncher


@tool("fn_test.add")
def add(a: int, b: int = 1) -> dict:
    """Add two numbers."""
    return {"sum": a + b}


@tool("fn_test.scale")
def scale(value: float, factor: Param[float]) -> dict:
    return {"scaled": value * factor}


@actor(type="fn_test_class")
class ClassActor(Actor):
    @tool(name="noop")
    def noop(self) -> dict:
        return {}


def test_function_stays_callable():
    assert add(2, 3) == {"sum": 5}


def test_functions_of_one_type_share_an_actor():
    cls = get_actor_class("fn_test")

    assert add._actor_type == "fn_test"
    assert set(cls().list_tools()) == {"add", "scale"}


def test_function_tool_executes_with_inputs_and_params():
    instance = get_actor_class("fn_test")()

    assert instance.execute_task(Task(id="t", type="fn_test.add", inputs=[TaskInput(name="a", value=2)])) == {"sum": 3}
    task = Task(id="t", type="fn_test.scale", inputs=[TaskInput(name="value", value=2.0)], params=[TaskParam(name="factor", value=1.5)])
    assert instance.execute_task(task) == {"scaled": 3.0}


def test_function_tool_cannot_join_an_actor_class():
    with pytest.raises(ValueError, match="ClassActor"):

        @tool("fn_test_class.extra")
        def extra() -> dict:
            return {}


def test_launcher_runs_function_tools():
    launcher = ActorLauncher(actor_types=["fn_test"], discover=False, transport=InMemoryTransport())

    assert list(launcher.actors) == ["fn_test"]


def test_run_accepts_a_function_tool(monkeypatch):
    launched = []
    monkeypatch.setattr(serve_module, "serve_forever", lambda launcher, on_stop=None: launched.append(launcher))

    run(add, transport=InMemoryTransport())

    assert list(launched[0].actors) == ["fn_test"]


def test_cli_runs_the_function_tools_of_a_file(monkeypatch, tmp_path):
    launched = []
    monkeypatch.setattr(serve_module, "serve_forever", lambda launcher, on_stop=None: launched.append(launcher))
    monkeypatch.setattr("antikythera_actors.launcher._get_eve_transport", lambda **kwargs: InMemoryTransport())
    path = tmp_path / "function_actor.py"
    path.write_text(
        textwrap.dedent(
            """
            from antikythera_actors import tool

            @tool("from_function_file.hello")
            def hello(name: str) -> dict:
                return {"greeting": name}
            """
        )
    )

    cli.main(["run", "--actor", str(path)])

    assert list(launched[0].actors) == ["from_function_file"]
