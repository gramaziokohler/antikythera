# Writing actors

An actor is a Python class that does tasks. Its methods marked with `@tool` are its tools.
A task of type `greeter.hello` is done by the `hello` tool of the actor of type `greeter`:

```python
from antikythera import Actor, actor, tool


@actor(type="greeter")
class Greeter(Actor):
    @tool(name="hello")
    def hello(self, name: str) -> dict:
        """Greet someone by name."""
        return {"greeting": f"Hello, {name}!"}
```

An actor with a single tool can be a plain function. Give `@tool` the full task type,
actor type and tool name, and Antikythera creates the actor for you:

```python
from antikythera import tool


@tool("greeter.hello")
def hello(name: str) -> dict:
    """Greet someone by name."""
    return {"greeting": f"Hello, {name}!"}
```

Functions with the same actor type, like `saw.cut` and `saw.measure`, become tools of one
actor. Write a class instead when the tools share something, like a connection to a
machine: open it in `__init__` and close it in `dispose`.

## Inputs, params and outputs

Antikythera looks at the arguments of a tool to know what to give it:

```python
from antikythera import Param


@tool(name="drill")
def drill(self, position: list, depth: Param[float] = 10.0) -> dict:
    ...
    return {"hole_id": hole_id}
```

- A plain argument, like `position`, is a task **input**, read from the session data.
- An argument marked `Param[...]`, like `depth`, is a task **param**, a fixed setting from
  the blueprint.
- An argument with a default value is optional.
- The tool returns a dictionary. Each key is an **output** of the task.

If a task does not give a tool what it needs, the task fails with the error
`TOOL_BINDING_ERROR`, and the tool does not run. If the tool raises an exception, the task
fails with `TOOL_FAILURE`. Either way, the session fails with that error. You can fix
the problem and run the task again from the web UI.

A tool can also ask for:

| Argument | Gives the tool |
| --- | --- |
| `context: ExecutionContext` | A way to know if the task was cancelled, to stop a long job early |
| `task: Task` | The whole task, for tools that need to read it directly |
| `element_id: Context[str]` | The model element being worked on, in a [dynamic expansion](concepts.md#more-features) |

The [reference actor](https://github.com/gramaziokohler/antikythera/blob/main/src/antikythera_actors/reference_actor.py)
uses all of these. It is a good file to copy from.

Write a docstring for every tool. `antikythera-actors describe` prints the tools of every
installed actor as JSON, with their docstrings, inputs, params and outputs, so people
writing blueprints know what each tool needs.

## Running actors

Actors connect to the orchestrator over the network, so they can run on any machine that
can reach it: the computer next to a robot, a laptop, a GPU server. By default they connect
to an MQTT broker. There are three ways to start them.

### With uvx

[uv](https://docs.astral.sh/uv/)'s `uvx` runs a program without installing it first. Point
`antikythera-actors` at the file with your actors:

```bash
uvx --from antikythera-sdk antikythera-actors run --actor greeter.py --broker-host mqtt.example.org
```

`--actor` takes a `.py` file or a module name, and can be given more than once. Only the
actors in those files run. Add the packages your actor needs with `--with`:

```bash
uvx --from antikythera-sdk --with compas_fab antikythera-actors run --actor robot_cell.py
```

### As a script

An actor file can also start itself. List its dependencies in an
[inline script header](https://packaging.python.org/en/latest/specifications/inline-script-metadata/)
and call `run()`:

```python
# /// script
# dependencies = ["antikythera-sdk"]
# ///
from antikythera import run, tool


@tool("greeter.hello")
def hello(name: str) -> dict:
    return {"greeting": f"Hello, {name}!"}


if __name__ == "__main__":
    run(hello)
```

```bash
MQTT_BROKER_HOST=mqtt.example.org uv run greeter.py
```

### As an installed package

To share actors, put them in a Python package and register them as a plugin in its
`pyproject.toml`:

```toml
[project.entry-points.'antikythera.actors']
robot = "my_robot_actors.robot"
```

Once the package is installed, `antikythera-actors run` finds and starts its actors with
all the others. `--only robot` runs only the actors of that type:

```bash
uvx --from antikythera-sdk --with my-robot-actors antikythera-actors run --only robot
```

The same command works in tools that start programs from a configuration file, the way MCP
clients start MCP servers:

```json
{
  "command": "uvx",
  "args": ["--from", "antikythera-sdk", "antikythera-actors", "run", "--actor", "/path/to/greeter.py"],
  "env": { "MQTT_BROKER_HOST": "mqtt.example.org" }
}
```

## Options

| Option | Default | |
| --- | --- | --- |
| `--broker-host` | `MQTT_BROKER_HOST`, or `127.0.0.1` | MQTT broker host |
| `--broker-port` | `MQTT_BROKER_PORT`, or `1883` | MQTT broker port |
| `--mqtt-transport` | `tcp` | `tcp` or `websockets` |
| `--tls` | off | Connect to the broker over TLS |
| `--transport` | `ANTIKYTHERA_TRANSPORT`, or `mqtt` | `mqtt`, `nats` or `zenoh`; see [NATS](nats.md) and [Zenoh](zenoh.md) |
| `--actor FILE_OR_MODULE` | | Run only the actors in this file or module. Repeatable |
| `--only ACTOR_TYPE` | | Run only actors of this type. Repeatable |
| `--sys-only` | off | Run only the `system` actor |
| `--dev` | off | Reload actors when their files change |
