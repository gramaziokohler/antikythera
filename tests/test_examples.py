"""Every blueprint in examples/ runs to completion with the actors that ship with Antikythera.

The orchestrator runs in-process (in-memory transport and storage), the built-in Python
actors run for real, and two stand-ins replace a person: one answers the terminal prompts
of `user_interaction.user_input`, the other plays the web UI's `user_prompt` actor.
"""

import builtins
import glob
import os
import time

import pytest
from compas_eve.codecs import ProtobufMessageCodec
from compas_eve.memory import InMemoryTransport
from compas_model.elements import Element
from compas_model.models import Model

import antikythera_orchestrator.system_actors as system_actors
from antikythera.io import BlueprintJsonSerializeV1
from antikythera.models import BlueprintSession
from antikythera.models import BlueprintSessionState
from antikythera.models import Task
from antikythera.models import TaskState
from antikythera_actors import Actor
from antikythera_actors import ActorLauncher
from antikythera_actors import actor
from antikythera_actors import tool
from antikythera_orchestrator import InMemoryStorage
from antikythera_orchestrator import Orchestrator

EXAMPLES = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..", "examples", "*.json")))
MODEL_ID = "example-model"
ELEMENT_COUNT = 3

# What the stand-in for the web UI answers to `user_prompt.confirm`, per task id.
ANSWERS = {}


@actor(type="user_prompt")
class UserPromptStandIn(Actor):
    """Plays the web UI's `user_prompt` actor: picks the configured answer, or the first option."""

    @tool(name="confirm")
    def confirm(self, task: Task) -> dict:
        options = task.get_param_value("options") or ["OK"]
        # Actors receive fully qualified ids, "<blueprint id>.<task id>".
        return {"result": ANSWERS.get(task.id.split(".")[-1], options[0])}


@pytest.fixture(scope="module")
def storage():
    """Every example blueprint is uploaded, so composite tasks find their inner blueprints."""
    storage = InMemoryStorage()
    with storage.blueprint_storage() as blueprints:
        for path in EXAMPLES:
            blueprints.add_blueprint(BlueprintJsonSerializeV1.from_file(path))
    model = Model()
    for _ in range(ELEMENT_COUNT):
        model.add_element(Element())
    with storage.model_storage() as models:
        models.add_model(MODEL_ID, model)
    return storage


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    real_sleep = time.sleep
    monkeypatch.setattr(system_actors.time, "sleep", lambda seconds: real_sleep(min(seconds, 0.01)))
    monkeypatch.setattr(builtins, "input", lambda prompt="": "typed answer")
    ANSWERS.clear()


def _run(path, storage, bsid):
    blueprint = BlueprintJsonSerializeV1.from_file(path)
    params = {"model_id": MODEL_ID} if os.path.basename(path) == "toy_problem_6.json" else {}
    transport = InMemoryTransport(codec=ProtobufMessageCodec())
    launcher = ActorLauncher(transport=transport)
    launcher.start()
    try:
        orchestrator = Orchestrator(BlueprintSession(bsid=bsid, blueprint=blueprint, params=params), transport=transport, storage=storage)
        orchestrator.start()
        assert orchestrator.await_completion(timeout=20), f"{os.path.basename(path)} did not finish"
        return orchestrator
    finally:
        launcher.stop()


def _states(orchestrator):
    return {data["task"].id: data["task"].state for _, data in orchestrator.graph.nodes(data=True)}


@pytest.mark.parametrize("path", EXAMPLES, ids=[os.path.basename(p) for p in EXAMPLES])
def test_example_completes(path, storage):
    orchestrator = _run(path, storage, bsid=f"example-{os.path.basename(path)}")

    assert orchestrator.session.state == BlueprintSessionState.COMPLETED, orchestrator.session.last_task_error


def test_example_ids_are_unique():
    ids = [BlueprintJsonSerializeV1.from_file(path).id for path in EXAMPLES]

    assert len(ids) == len(set(ids))


def test_toy_problem_6_runs_once_per_model_element(storage):
    orchestrator = _run(os.path.join(os.path.dirname(EXAMPLES[0]), "toy_problem_6.json"), storage, bsid="tp6-elements")

    expanded = [task_id for task_id in _states(orchestrator) if task_id.startswith("X1_")]
    assert len(expanded) == ELEMENT_COUNT


def test_toy_problem_8_skips_the_second_question_when_the_answer_is_no(storage):
    ANSWERS["A1-ask-user"] = "No"

    orchestrator = _run(os.path.join(os.path.dirname(EXAMPLES[0]), "toy_problem_8.json"), storage, bsid="tp8-no")

    states = _states(orchestrator)
    assert states["A1-extra"] == TaskState.SKIPPED
    assert states["B1"] == TaskState.SUCCEEDED


def test_scope_skip_skips_the_scope(storage):
    orchestrator = _run(os.path.join(os.path.dirname(EXAMPLES[0]), "scope_skip.json"), storage, bsid="scope-skip")

    states = _states(orchestrator)
    assert {states[t] for t in ("scope_open", "do_work", "scope_close")} == {TaskState.SKIPPED}
    assert states["post_scope_task"] == TaskState.SUCCEEDED


def _load_example(name):
    import importlib.util

    path = os.path.join(os.path.dirname(EXAMPLES[0]), name)
    spec = importlib.util.spec_from_file_location(f"example_{name[:-3]}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_embedded_example_computes_the_answer():
    assert _load_example("embedded.py").main() == 42


def test_greeter_example_defines_an_actor():
    greeter = _load_example("greeter_actor.py").Greeter

    assert greeter._actor_type == "greeter"
    assert greeter().hello("world") == {"greeting": "Hello, world!"}


def test_hello_world_example_prints_the_greeting(capsys):
    _load_example("hello_world.py")

    assert capsys.readouterr().out.splitlines()[-1] == "Hello, world!"
