# Run with Docker

This is the recommended way to run Antikythera. The orchestrator, the system agents
and the web UI are published as images on Docker Hub, so nothing has to be cloned,
built or installed — one compose file starts the whole system.

## Prerequisites

* [Docker](https://docs.docker.com/get-started/get-docker/) with the Compose plugin
  (v2.23.1 or newer — Docker Desktop 4.26+ ships it). Check with `docker compose version`.
* Roughly 2 GB of disk for the images.

## Quick start

Download the deployment compose file and start the stack:

```bash
curl -O https://raw.githubusercontent.com/gramaziokohler/antikythera/main/deploy/docker-compose.yml
docker compose up -d
```

Then open <http://localhost:8080>.

That's it. The first run pulls the images, which takes a few minutes; subsequent
starts are immediate.

!!! note
    Run the commands from the directory holding the downloaded `docker-compose.yml` —
    `docker compose` always acts on the file in the current directory.

## What is running

| Service | Image | Host port | Purpose |
| --- | --- | --- | --- |
| `frontend` | `gramaziokohler/antikythera-frontend` | 8080 | Web UI, proxies `/api` to the orchestrator |
| `orchestrator` | `gramaziokohler/antikythera` | 8000 | REST API — schedules and tracks sessions |
| `agents` | `gramaziokohler/antikythera` | — | The built-in `system.*`, `io.*` and `user_interaction.*` agents |
| `mqtt-broker` | `eclipse-mosquitto` | 1883, 8083 | Message bus between orchestrator and agents |
| `redis` | `redis` | — | Stores blueprints, sessions and session data |

Redis is deliberately not published to the host — only the orchestrator talks to it.
The MQTT broker *is* published, because agents running on other machines connect to it.

## Agents

The `agents` service runs every agent that ships with Antikythera — the `system.*`,
`io.*` and `user_interaction.*` task types. That is what the example blueprints need, so
they run to completion out of the box. Adding `--sys-only` to that service's command
restricts it to `system.*`; a blueprint using any other first-party type then stalls
indefinitely on a task no agent claims.

### Connecting your own agents

Agents for your own hardware do not run inside this stack. They run wherever the hardware is — a workshop PC,
a robot controller, a Grasshopper session — and connect to the MQTT broker over the network:

```bash
pip install antikythera-sdk
antikythera-agents run --broker-host <host-running-docker> --broker-port 1883
```

The dashboard in the web UI shows the broker address to use, with a button to copy it.

!!! warning
    The UI derives that address from the port the broker is normally published on (1883).
    If you change `AKT_MQTT_PORT` below, the address shown will be wrong — adjust the port
    yourself when configuring agents.

## The MCP server

An MCP server that lets an LLM client author blueprints and drive sessions ships in the
same image but stays off by default. Start it with:

```bash
docker compose --profile mcp up -d
```

Clients then connect to `http://localhost:8001/sse`.

## Configuration

Every published port can be changed with an environment variable. Put them in a `.env`
file next to `docker-compose.yml`:

```bash
AKT_WEB_PORT=80          # web UI            (default 8080)
AKT_API_PORT=8000        # orchestrator API  (default 8000)
AKT_MQTT_PORT=1883       # MQTT over TCP     (default 1883)
AKT_MQTT_WS_PORT=8083    # MQTT over WebSocket (default 8083)
AKT_MCP_PORT=8001        # MCP server        (default 8001)
```

Apply changes with `docker compose up -d` — Compose recreates only what changed.

## Day-to-day

```bash
docker compose ps                    # what is running
docker compose logs -f orchestrator  # follow the orchestrator log
docker compose stop                  # stop, keep data
docker compose up -d                 # start again
docker compose down                  # stop and remove containers, keep data
```

**Updating** to the newest published images:

```bash
docker compose pull
docker compose up -d
```

Both images are tagged `latest`, which is the pair released together — the backend and the
frontend are versioned independently, so there is no matching version number to pin them
to. If you need a deployment frozen against updates, replace `latest` with a specific tag
in `docker-compose.yml` and verify that combination yourself.

**Data** — blueprints, sessions and session data live in Redis, in the `antikythera_redis-data`
volume. It survives `stop`, `down`, and image updates. To back it up:

```bash
docker compose exec redis redis-cli SAVE
docker run --rm -v antikythera_redis-data:/data -v "$PWD:/backup" \
  alpine tar czf /backup/antikythera-backup.tar.gz -C /data .
```

To wipe everything and start clean:

```bash
docker compose down -v
```

## Security

Antikythera is built for a trusted network — a lab, a workshop, a fabrication cell.
There is **no authentication** on the REST API and the MQTT broker accepts anonymous
connections. Anyone who can reach these ports can start, stop and delete sessions.

Do not expose ports 8080, 8000, 1883, 8083 or 8001 to the public internet. If access from
outside the local network is needed, put it behind a VPN or an authenticating reverse proxy.

## Troubleshooting

**Port already in use** — something else on the machine holds port 8080 (or 8000, 1883).
Set the corresponding `AKT_*_PORT` in `.env` and run `docker compose up -d` again.

**UI loads but shows no data** — the orchestrator is not reachable. Check
`docker compose ps` for a service that is not `running`, then `docker compose logs orchestrator`.

**A session stalls with a task stuck on READY** — no running agent handles that task type.
Check `docker compose logs agents` to see which agents started, and confirm any agent of
your own is pointed at the same broker as the orchestrator: the host and port passed to
`antikythera-agents run` must match the address shown on the dashboard, with port 1883
open on the machine running Docker.

**`configs` top-level element error** — the Compose plugin is older than v2.23.1. Update
Docker, or copy the `mosquitto` config block into a local `mosquitto.conf` and mount it
as a volume instead.

## Running from a clone

If you are working on Antikythera itself, use the `docker-compose.yml` in the repository
root instead. It builds both images from local source (the frontend from a sibling
`antikythera-frontend` checkout) and runs the orchestrator with auto-reload. See
[Installation](../installation.md).
