# Running on NATS

By default, Antikythera needs two services: an MQTT broker to carry messages between the
orchestrator and the actors, and Redis to keep its data. One [NATS](https://nats.io/)
server can do both: NATS carries the messages, and its JetStream feature keeps sessions,
blueprints and models.

Install the extra and start a server:

```bash
pip install "antikythera-sdk[deployment,nats]"
docker run -p 4222:4222 nats -js
```

## The service

Choose NATS with environment variables:

```bash
export ANTIKYTHERA_TRANSPORT=nats
export ANTIKYTHERA_STORAGE=nats
export NATS_URL=nats://localhost:4222
antikythera
```

| Variable | Default | |
| --- | --- | --- |
| `ANTIKYTHERA_TRANSPORT` | `mqtt` | `mqtt`, `nats` or `zenoh` |
| `ANTIKYTHERA_STORAGE` | `redis` | `redis`, `nats`, `zenoh` or `memory` |
| `NATS_URL` | `nats://127.0.0.1:4222` | Server URL; `tls://` for TLS |
| `NATS_STORAGE_PREFIX` | `antikythera` | Prefix of the storage buckets, so several installations can share a server |

Transport and storage are separate choices: NATS for messages and Redis for data works,
and so does the other way around.

## Actors

```bash
antikythera-actors run --transport nats --nats-url nats://localhost:4222
uvx --from "antikythera-sdk[nats]" antikythera-actors run --transport nats --actor my_actor.py
```

`ANTIKYTHERA_TRANSPORT` and `NATS_URL` work here too, and in `antikythera_actors.run()`.

## From Python

```python
from compas_eve.codecs import ProtobufMessageCodec

from antikythera.transports.nats import NatsTransport
from antikythera_orchestrator import Orchestrator
from antikythera_orchestrator.storage.nats_storage import NatsStorage

orchestrator = Orchestrator(
    session,
    transport=NatsTransport("nats://localhost:4222", codec=ProtobufMessageCodec()),
    storage=NatsStorage("nats://localhost:4222"),
)
```

## The web UI and MQTT actors

The web UI talks MQTT over WebSocket (`ws://<host>:8083/mqtt`). A NATS server can speak
MQTT and WebSocket as well, so the web UI and existing MQTT actors work with it unchanged.
Turn both on in the server configuration:

```
# nats.conf
server_name: antikythera
jetstream { store_dir: /data }
mqtt { port: 1883 }
websocket { port: 8083, no_tls: true }
```

```bash
docker run -p 4222:4222 -p 1883:1883 -p 8083:8083 -v $PWD/nats.conf:/nats.conf nats -c /nats.conf
```

MQTT topics and NATS subjects are matched automatically (`antikythera/task/start` is
`antikythera.task.start`), so you can also move an installation to NATS one part at a
time. This setup was tested with NATS 2.10 and 2.15, with the web UI answering a question,
and no MQTT broker or Redis running. In production, use TLS for the WebSocket port, as
with any broker.

The NATS transport is part of Antikythera for now (`antikythera.transports.nats`). It
will move to `compas_eve` later.
