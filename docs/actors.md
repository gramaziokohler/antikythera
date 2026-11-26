# Running actors

An actor is a Python class whose methods are tools. A task of type `greeter.hello` is run by
the `hello` tool of the actor registered as `greeter`:

```python
from antikythera_actors import Actor, actor, tool


@actor(type="greeter")
class Greeter(Actor):
    @tool(name="hello")
    def hello(self, name: str) -> dict:
        return {"greeting": f"Hello, {name}!"}
```

Actors connect to the orchestrator over MQTT, so they can run on any machine that reaches
the broker: a robot cell controller, a laptop next to a CNC, a GPU server. There are three
ways to start them, from no setup at all to a full installation.

## With uvx, from a file

[uv](https://docs.astral.sh/uv/)'s `uvx` runs a command from a package without installing it
first. Point `antikythera-actors` at the file that defines your actors:

```bash
uvx --from antikythera-sdk antikythera-actors run --actor greeter.py --broker-host mqtt.example.org
```

`--actor` accepts a `.py` file or an importable module name and can be repeated. Only the
actors defined there run, so the built-in actors of the main stack are not started a second
time. Add the packages your actor needs with `--with`:

```bash
uvx --from antikythera-sdk --with compas_fab antikythera-actors run --actor robot_cell.py
```

If your actors are an installed package that registers them in the `antikythera.actors`
entry point group, add it with `--with` and leave out `--actor`. `--only` then picks which of
the installed actors run:

```bash
uvx --from antikythera-sdk --with my-robot-actors antikythera-actors run --only robot
```

## As a script

Like an MCP server started with `mcp.run()`, an actor file can start itself. Declare its
dependencies in an [inline script header](https://packaging.python.org/en/latest/specifications/inline-script-metadata/)
and call `run()`:

```python
# /// script
# dependencies = ["antikythera-sdk"]
# ///
from antikythera_actors import Actor, actor, run, tool


@actor(type="greeter")
class Greeter(Actor):
    @tool(name="hello")
    def hello(self, name: str) -> dict:
        return {"greeting": f"Hello, {name}!"}


if __name__ == "__main__":
    run(Greeter)
```

```bash
MQTT_BROKER_HOST=mqtt.example.org uv run greeter.py
```

`run()` takes the actor classes to run, and the broker as keyword arguments or from the
`MQTT_BROKER_HOST` and `MQTT_BROKER_PORT` environment variables.

## From a process manager or client configuration

Clients that launch tools as subprocesses, the way MCP clients launch MCP servers, can start
an actor with the same command and arguments:

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
| `--actor FILE_OR_MODULE` | | Run only the actors defined there. Repeatable |
| `--only ACTOR_TYPE` | | Run only actors of this type. Repeatable |
| `--sys-only` | off | Run only the `system` actor |
| `--dev` | off | Reload installed actor plugins when their files change |

`antikythera-actors describe` prints the tools of every installed actor as JSON, the catalog
blueprint authors work from.
