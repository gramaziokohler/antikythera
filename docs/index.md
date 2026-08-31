# Antikythera

<p align="center">
  <img src="_images/antikythera.png" alt="Antikythera">
</p>

<p class="lead" align="center">
An all knowing, all controlling, robotic and otherwise, process manager.
</p>

## Quick start

The orchestrator, the system agents and the web UI are published as Docker images.
Nothing needs to be cloned or built — download the deployment compose file and start it:

```bash
curl -O https://raw.githubusercontent.com/gramaziokohler/antikythera/main/deploy/docker-compose.yml
docker compose up -d
```

Then open <http://localhost:8080>.

See [Run with Docker](deployment/docker.md) for what is running, how to connect your own
agents, and how to configure it. To run without Docker, see
[Run on bare metal](deployment/bare-metal.md).

## Install the SDK

To write blueprints and agents, or to talk to a running orchestrator from Python,
install the SDK from PyPI.

```bash
pip install antikythera-sdk
```

To also install the orchestrator and its deployment dependencies — for running the server
yourself rather than in a container:

```bash
pip install antikythera-sdk[deployment]
```

More in [Installation](installation.md).
