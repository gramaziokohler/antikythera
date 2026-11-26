# Installation

You need the Python package to write actors and blueprints, or to run the orchestrator
inside your own program. To run the full system with the web UI, you only need Docker:
see [Run with Docker](deployment/docker.md).

## Install

Antikythera needs Python 3.9 or newer.

```bash
pip install antikythera-sdk
```

This is enough to write actors, and to run blueprints in your own Python program.
Optional extras add more:

| Extra | Adds |
| --- | --- |
| `deployment` | The orchestrator service with its HTTP API (`antikythera` command), used by the web UI |
| `mcp` | The MCP server (`antikythera-mcp` command), so LLM clients can write and run blueprints |
| `nats` | [NATS](nats.md) instead of MQTT and Redis |
| `zenoh` | [Zenoh](zenoh.md) instead of MQTT and Redis |

```bash
pip install "antikythera-sdk[deployment,mcp]"
```

## Models from other packages

Antikythera works with [compas_model](https://github.com/blockresearchgroup/compas_model)
models. A model made with another package, such as
[compas_timber](https://github.com/gramaziokohler/compas_timber), can only be loaded where
that package is installed. Install it next to Antikythera:

```bash
pip install antikythera-sdk compas_timber
```

Without it, uploading a timber model fails with a message that names the missing package.
The Docker images already include compas_timber.

## From source

To work on Antikythera itself:

```bash
git clone https://github.com/gramaziokohler/antikythera.git
cd antikythera
pip install -e ".[dev]"
invoke pre-build  # generates the protobuf code
```

The `docker-compose.yml` at the root of the repository builds the images from your clone
and restarts the orchestrator when the code changes. It needs a checkout of
[antikythera-frontend](https://github.com/gramaziokohler/antikythera-frontend) next to
this one:

```bash
docker compose build
docker compose up -d
```

To only *use* Antikythera, follow [Run with Docker](deployment/docker.md) instead. It
downloads the published images and builds nothing.
