# Running on NATS

By default Antikythera needs two services next to it: an MQTT broker for the messages
between the orchestrator and the actors, and Redis for its state. A single
[NATS](https://nats.io/) server with JetStream can do both: NATS carries the messages, and
JetStream object stores keep sessions, blueprints and models.

Install the extra and start a server:

```bash
pip install "antikythera-sdk[deployment,nats]"
docker run -p 4222:4222 nats -js
```

## The service

Choose NATS for the transport and the storage with environment variables:

```bash
export ANTIKYTHERA_TRANSPORT=nats
export ANTIKYTHERA_STORAGE=nats
export NATS_URL=nats://localhost:4222
antikythera
```

| Variable | Default | |
| --- | --- | --- |
| `ANTIKYTHERA_TRANSPORT` | `mqtt` | `mqtt` or `nats` |
| `ANTIKYTHERA_STORAGE` | `redis` | `redis`, `nats` or `memory` |
| `NATS_URL` | `nats://127.0.0.1:4222` | Server URL; `tls://` for TLS |
| `NATS_STORAGE_PREFIX` | `antikythera` | Prefix of the object store buckets, so deployments can share a server |

Storage and transport are independent: NATS messages with Redis storage, or MQTT with NATS
storage, work as well.

## Actors

```bash
antikythera-actors run --transport nats --nats-url nats://localhost:4222
uvx --from "antikythera-sdk[nats]" antikythera-actors run --transport nats --actor my_actor.py
```

`ANTIKYTHERA_TRANSPORT` and `NATS_URL` set the defaults here too, and for
`antikythera_actors.run()`.

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

The web UI connects with MQTT over WebSocket (`ws://<host>:8083/mqtt`), and existing
actors may speak plain MQTT. The NATS server serves both: enable its MQTT and WebSocket
listeners, and they exchange messages with the orchestrator on NATS unchanged.
`NatsTransport` maps topic names the way the server's MQTT support does
(`antikythera/task/start` is the subject `antikythera.task.start`), so a deployment can
also move to NATS one piece at a time.

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

The WebSocket listener hands connections on the `/mqtt` path to the MQTT layer, so the
browser needs no change. This was tested with the web UI answering a `user_prompt` task
on NATS 2.10 and 2.15, with no MQTT broker and no Redis running. In production, put the
WebSocket listener behind TLS (a `tls` block in `websocket`, or a reverse proxy), as with
any broker.

The NATS transport lives in Antikythera for now (`antikythera.transports.nats`) and is
meant to move to `compas_eve` once it has proven itself.
