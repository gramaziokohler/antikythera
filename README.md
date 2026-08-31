<div align="center">

[![Made with COMPAS](https://compas.dev/badge.svg)](https://compas.dev)
[![PyPI Package latest release](https://img.shields.io/pypi/v/antikythera-sdk.svg)](https://pypi.python.org/pypi/antikythera-sdk)
[![Docker Image Version](https://img.shields.io/docker/v/gramaziokohler/antikythera?logo=docker&label=backend)](https://hub.docker.com/r/gramaziokohler/antikythera)
[![Docker Image Version](https://img.shields.io/docker/v/gramaziokohler/antikythera-frontend?logo=docker&label=frontend)](https://hub.docker.com/r/gramaziokohler/antikythera-frontend)
[![License](https://img.shields.io/github/license/gramaziokohler/antikythera.svg)](https://pypi.python.org/pypi/antikythera-sdk)
[![DOI](https://zenodo.org/badge/1046154055.svg)](https://doi.org/10.5281/zenodo.20297856)


</div>

<h1><img src="docs/_images/antikythera_logo.png" alt="Antikythera" width="48" style="vertical-align: middle; margin-right: 8px;" /> Antikythera</h1>

> *An all knowing, all controlling, robotic and otherwise, process manager.*

<img src="docs/_images/antikythera.png" alt="Antikythera" />

Antikythera is an distributed system for orchestration of fabrication processes in the context of architecture and construction.

## Installation

Stable releases can be installed from PyPI.

```bash
pip install antikythera
```

To install the latest version for development, do:

```bash
git clone https://github.com/gramaziokohler/antikythera.git
cd antikythera
pip install -e ".[dev]"
```

## Documentation

For further "getting started" instructions, a tutorial, examples, and an API reference,
please check out the online documentation here: [antikythera docs](https://gramaziokohler.github.io/antikythera)

## Running Antikythera

The orchestrator, the system agents and the web UI are published as Docker images, so a
complete installation needs no clone and no build:

```bash
curl -O https://raw.githubusercontent.com/gramaziokohler/antikythera/main/deploy/docker-compose.yml
docker compose up -d
```

Then open <http://localhost:8080>. See [Run with Docker](https://gramaziokohler.github.io/antikythera/deployment/docker/)
for configuration, connecting your own agents, and updating, or
[Run on bare metal](https://gramaziokohler.github.io/antikythera/deployment/bare-metal/)
to run the services without Docker.

### Development stack

The `docker-compose.yml` in the repository root is the *development* setup: it builds both
images from local source (the frontend from a sibling `antikythera-frontend` checkout) and
runs the orchestrator with auto-reload.

```bash
docker compose build           # build the images (only needed once, or after code changes)
docker compose up -d           # start all services
```

## Issue Tracker

If you find a bug or if you have a problem with running the code, please file an issue on the [Issue Tracker](https://github.com/gramaziokohler/antikythera/issues).
