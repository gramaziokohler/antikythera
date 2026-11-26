"""Running a chosen set of actors: `antikythera-actors run --actor ...` and `antikythera_actors.run()`."""

import textwrap

import pytest
from compas_eve.codecs import ProtobufMessageCodec
from compas_eve.memory import InMemoryTransport

import antikythera_actors.serve as serve_module
from antikythera_actors import Actor
from antikythera_actors import actor
from antikythera_actors import cli
from antikythera_actors import run
from antikythera_actors import tool
from antikythera_actors.launcher import ActorLauncher


@actor(type="run_test")
class RunTestActor(Actor):
    @tool(name="echo")
    def echo(self, value: int) -> dict:
        return {"value": value}


@pytest.fixture
def launched(monkeypatch):
    """Capture the launcher instead of blocking on it, and never open an MQTT connection."""
    launchers = []
    monkeypatch.setattr("antikythera_actors.launcher._get_eve_transport", lambda **kwargs: InMemoryTransport(codec=ProtobufMessageCodec()))
    monkeypatch.setattr(serve_module, "serve_forever", lambda launcher, on_stop=None: launchers.append(launcher))
    monkeypatch.setattr("antikythera_actors.launcher._ensure_actors", lambda: None)
    return launchers


@pytest.fixture
def actor_file(tmp_path):
    path = tmp_path / "file_actor.py"
    path.write_text(
        textwrap.dedent(
            """
            from antikythera_actors import Actor, actor, tool

            @actor(type="from_file")
            class FromFile(Actor):
                @tool(name="noop")
                def noop(self) -> dict:
                    return {}
            """
        )
    )
    return path


def test_launcher_runs_only_requested_actor_types():
    launcher = ActorLauncher(actor_types=["run_test"], discover=False, transport=InMemoryTransport(codec=ProtobufMessageCodec()))

    assert list(launcher.actors) == ["run_test"]


def test_launcher_rejects_unknown_actor_type():
    with pytest.raises(ValueError, match="no_such_actor"):
        ActorLauncher(actor_types=["no_such_actor"], discover=False, transport=InMemoryTransport(codec=ProtobufMessageCodec()))


def test_run_starts_only_the_given_actors(launched):
    run(RunTestActor)

    assert list(launched[0].actors) == ["run_test"]
    assert launched[0].discover is False


def test_run_rejects_classes_that_are_not_actors(launched):
    class NotAnActor:
        pass

    with pytest.raises(TypeError, match="@actor"):
        run(NotAnActor)


def test_cli_runs_the_actors_of_a_file(launched, actor_file):
    cli.main(["run", "--actor", str(actor_file)])

    assert list(launched[0].actors) == ["from_file"]


def test_cli_runs_the_actors_of_a_module(launched, actor_file, monkeypatch):
    monkeypatch.syspath_prepend(str(actor_file.parent))

    cli.main(["run", "--actor", "file_actor"])

    assert list(launched[0].actors) == ["from_file"]


def test_cli_only_filters_installed_actors(launched):
    cli.main(["run", "--only", "run_test"])

    assert list(launched[0].actors) == ["run_test"]
    assert launched[0].discover is True


def test_cli_reports_files_without_actors(launched, tmp_path):
    empty = tmp_path / "empty.py"
    empty.write_text("x = 1\n")

    with pytest.raises(SystemExit, match="No actors found"):
        cli.main(["run", "--actor", str(empty)])


def test_cli_reports_unknown_actor_types(launched):
    with pytest.raises(SystemExit, match="Unknown actor type"):
        cli.main(["run", "--only", "no_such_actor"])


def test_cli_dev_cannot_reload_actor_files(launched, actor_file):
    with pytest.raises(SystemExit, match="--dev"):
        cli.main(["run", "--dev", "--actor", str(actor_file)])
