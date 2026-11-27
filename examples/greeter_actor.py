# /// script
# dependencies = ["antikythera-sdk"]
# ///
"""An actor in a single file.

Run it as a script, uv reads the dependencies from the header above:

    MQTT_BROKER_HOST=localhost uv run examples/greeter_actor.py

or without the `run()` call, through the command line:

    uvx --from antikythera-sdk antikythera-actors run --actor examples/greeter_actor.py

Then start a blueprint with a task of type `greeter.hello`, for example:

    {"id": "hello", "type": "greeter.hello", "inputs": [{"name": "name", "value": "world"}], "outputs": [{"name": "greeting"}]}
"""

from antikythera_actors import Actor
from antikythera_actors import actor
from antikythera_actors import run
from antikythera_actors import tool


@actor(type="greeter")
class Greeter(Actor):
    @tool(name="hello")
    def hello(self, name: str) -> dict:
        """Greet someone by name."""
        return {"greeting": f"Hello, {name}!"}


if __name__ == "__main__":
    run(Greeter)
