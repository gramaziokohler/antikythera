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

## Mixing MQTT and NATS

`NatsTransport` maps topic names the way the NATS server's own MQTT support does:
`antikythera/task/start` is the subject `antikythera.task.start`. With MQTT enabled on the
server, actors that speak MQTT connect to it unchanged and work with an orchestrator on
NATS. That lets a deployment move to NATS one piece at a time:

```
# nats.conf
server_name: antikythera
jetstream {}
mqtt { port: 1883 }
```

```bash
docker run -p 4222:4222 -p 1883:1883 -v $PWD/nats.conf:/nats.conf nats -c /nats.conf
```

The NATS transport lives in Antikythera for now (`antikythera.transports.nats`) and is
meant to move to `compas_eve` once it has proven itself.
