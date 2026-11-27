# Installation

This page covers installing the Python package — the SDK, and optionally the orchestrator
itself. To *run* Antikythera (orchestrator, actors and web UI) you do not need any of it:
see [Run with Docker](deployment/docker.md).

## Stable

Stable releases are available on PyPI and can be installed with pip.

```bash
pip install antikythera-sdk
```

This is enough to run an orchestrator and actors from your own Python code. Extras add
the network services:

* `deployment`: the HTTP API service (`antikythera` command) that the web UI talks to.
* `mcp`: the MCP server (`antikythera-mcp` command).
* `nats`: the NATS transport and storage, see [Running on NATS](nats.md).

```bash
pip install "antikythera-sdk[deployment,mcp]"
```

### Domain models

Antikythera works with any [compas_model](https://github.com/blockresearchgroup/compas_model)
model, and only depends on that. Models made with a domain package, such as
[compas_timber](https://github.com/gramaziokohler/compas_timber), can only be loaded where
that package is installed, so install it next to Antikythera:

```bash
pip install antikythera-sdk compas_timber
```

Without it, uploading a timber model is rejected with a message naming the missing
package. The Docker images include compas_timber.

## Latest

The latest version can be installed from local source.

```bash
git clone https://github.com/gramaziokohler/antikythera.git
cd antikythera
pip install -e .
```

## Development

To install `antikythera` for development, install from local source with the "dev" requirements.

```bash
git clone https://github.com/gramaziokohler/antikythera.git
cd antikythera
pip install -e ".[dev]"
invoke pre-build  # generates the protobuf bindings
```

To bring up the full stack from your clone — both images built from local source, the
orchestrator running with auto-reload — use the `docker-compose.yml` in the repository
root. It expects a sibling checkout of
[antikythera-frontend](https://github.com/gramaziokohler/antikythera-frontend):

```bash
docker compose build
docker compose up -d
```

This is the development setup. For a normal installation, use the deployment compose file
described in [Run with Docker](deployment/docker.md) instead — it pulls published images
and builds nothing.
