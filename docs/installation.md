# Installation

This page covers installing the Python package — the SDK, and optionally the orchestrator
itself. To *run* Antikythera (orchestrator, agents and web UI) you do not need any of it:
see [Run with Docker](deployment/docker.md).

## Stable

Stable releases are available on PyPI and can be installed with pip.

```bash
pip install antikythera-sdk
```

This is enough to run an orchestrator and agents from your own Python code. Two extras
add the network services:

* `deployment`: the HTTP API service (`antikythera` command) that the web UI talks to.
* `mcp`: the MCP server (`antikythera-mcp` command).

```bash
pip install "antikythera-sdk[deployment,mcp]"
```

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
