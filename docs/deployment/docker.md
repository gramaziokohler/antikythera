# Run with Docker

This is the easiest way to run Antikythera. The orchestrator, the built-in actors and the
web UI are published as Docker images. One file starts all of them; you do not need to
download or build any code.

## Prerequisites

* [Docker](https://docs.docker.com/get-started/get-docker/) with the Compose plugin
  (v2.23.1 or newer; Docker Desktop 4.26 and newer have it). Check with `docker compose version`.
* Roughly 2 GB of disk for the images.

## Quick start

Download the deployment compose file and start the stack:

```bash
curl -O https://raw.githubusercontent.com/gramaziokohler/antikythera/main/deploy/docker-compose.yml
docker compose up -d
```

Then open <http://localhost:8080>.

The first start downloads the images, which takes a few minutes. Later starts are fast.

!!! note
    Run the commands in the folder with the downloaded `docker-compose.yml`.
    `docker compose` always uses the file in the current folder.

## What is running

| Service | Image | Host port | Purpose |
| --- | --- | --- | --- |
| `frontend` | `gramaziokohler/antikythera-frontend` | 8080 | Web UI, proxies `/api` to the orchestrator |
| `orchestrator` | `gramaziokohler/antikythera` | 8000 | HTTP API; runs and tracks sessions |
| `actors` | `gramaziokohler/antikythera` | | The built-in `system.*`, `io.*` and `user_interaction.*` actors |
| `mqtt-broker` | `eclipse-mosquitto` | 1883, 8083 | Message bus between orchestrator and actors |
| `redis` | `redis` | | Stores blueprints, sessions and session data |

Only the orchestrator talks to Redis, so its port is not open to other machines. The
MQTT broker port is open, because actors on other machines connect to it.

## Actors

The `actors` service runs the actors that come with Antikythera: `system`, `io` and
`user_interaction`. These are all the example blueprints need. With `--sys-only` added to
its command, it runs only `system`. A blueprint that uses another of these actors then
waits forever for a task that no actor takes.

### Connecting your own actors

Actors for your own machines do not run in Docker. They run where the machine is, for
example on a workshop computer or a robot controller, and connect to the MQTT broker over
the network:

```bash
pip install antikythera-sdk
antikythera-actors run --broker-host <host-running-docker> --broker-port 1883
```

The dashboard in the web UI shows the broker address to use, with a button to copy it.

!!! warning
    The UI assumes the broker uses port 1883. If you change `AKT_MQTT_PORT` below, the
    address it shows is wrong, so use your port when you start actors.

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

Apply changes with `docker compose up -d`. It restarts only what changed.

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

Both images use the `latest` tag. The backend and the frontend have separate version
numbers, so `latest` is the way to get two that work together. To stop updates, replace
`latest` with a specific version in `docker-compose.yml`, and check yourself that the two
versions work together.

**Data**: blueprints, sessions and session data are kept by Redis, in the
`antikythera_redis-data` volume. They are kept through `stop`, `down` and updates. To make
a backup:

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

Antikythera is made for a trusted network, like a lab or a workshop. There are **no
passwords**: anyone who can reach the HTTP API or the MQTT broker can start, stop and
delete sessions.

Do not expose ports 8080, 8000, 1883, 8083 or 8001 to the public internet. If access from
outside the local network is needed, put it behind a VPN or an authenticating reverse proxy.

## Troubleshooting

**Port already in use**: another program uses port 8080 (or 8000, or 1883).
Set the corresponding `AKT_*_PORT` in `.env` and run `docker compose up -d` again.

**The UI shows no data**: it cannot reach the orchestrator. Check
`docker compose ps` for a service that is not `running`, then `docker compose logs orchestrator`.

**A task stays READY and the session does not move on**: no running actor does that
task type. Check `docker compose logs actors` to see which actors started. Make sure your
own actors use the broker address shown on the dashboard, and that port 1883 is open on
the machine running Docker.

**Error about the `configs` element**: Docker Compose is older than v2.23.1. Update
Docker, or copy the `mosquitto` config block into a local `mosquitto.conf` and mount it
as a volume instead.

## Running from a clone

To work on Antikythera itself, use the `docker-compose.yml` at the root of the
repository instead. See [Installation](../installation.md#from-source).
