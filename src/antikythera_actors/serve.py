"""Run actors from a script, the way an MCP server runs with ``mcp.run()``.

A single file is enough to put an actor on the network:

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

Start it with ``uv run greeter.py``; uv reads the dependencies from the header, so there
is nothing to install first.
"""

from __future__ import annotations

import logging
import time
from typing import Callable
from typing import Optional

from compas_eve import Transport

from antikythera import config
from antikythera_actors import launcher as launcher_module
from antikythera_actors.launcher import ActorLauncher

LOG = logging.getLogger(__name__)


def run(
    *actors: type,
    broker_host: Optional[str] = None,
    broker_port: Optional[int] = None,
    mqtt_transport: str = "tcp",
    tls: bool = False,
    transport: Optional[Transport] = None,
) -> None:
    """Run actors until the process is interrupted (Ctrl+C).

    Parameters
    ----------
    *actors : type
        The actors to run: classes decorated with ``@actor``, or functions decorated with
        ``@tool("<actor_type>.<tool>")``. Without any, every
        registered actor runs, including the ones installed as plugins.
    broker_host : str, optional
        Host of the MQTT broker. Defaults to the ``MQTT_BROKER_HOST`` environment
        variable, or ``127.0.0.1``.
    broker_port : int, optional
        Port of the MQTT broker. Defaults to the ``MQTT_BROKER_PORT`` environment
        variable, or ``1883``.
    mqtt_transport : str, optional
        The MQTT socket transport, ``"tcp"`` or ``"websockets"``.
    tls : bool, optional
        Connect to the MQTT broker over TLS.
    transport : compas_eve.Transport, optional
        Use this transport instead of MQTT. It must use ``ProtobufMessageCodec``.
    """
    actor_types = None
    if actors:
        actor_types = []
        for cls in actors:
            actor_type = getattr(cls, "_actor_type", None)
            if actor_type is None:
                raise TypeError(f"{cls!r} is not an actor: decorate it with @actor(type=...), or a function with @tool('<actor_type>.<tool>')")
            actor_types.append(actor_type)

    if transport is None:
        transport = launcher_module._get_eve_transport(
            host=broker_host or config.MQTT_BROKER_HOST, port=broker_port or config.MQTT_BROKER_PORT, codec=None, transport=mqtt_transport, tls=tls
        )
    launcher = ActorLauncher(actor_types=actor_types, discover=not actors, transport=transport)
    serve_forever(launcher)


def serve_forever(launcher: ActorLauncher, on_stop: Optional[Callable[[], None]] = None) -> None:
    """Start ``launcher`` and keep it running until the process is interrupted.

    Parameters
    ----------
    launcher : ActorLauncher
        The launcher to run.
    on_stop : callable, optional
        Called after the launcher stopped, for extra cleanup.
    """
    launcher.start()
    print(f"Actors running: {', '.join(sorted(launcher.actors)) or 'none'}. Waiting for tasks, press Ctrl+C to stop.", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down actors...", flush=True)
    finally:
        launcher.stop()
        if on_stop:
            on_stop()
        print("Actors stopped.", flush=True)
