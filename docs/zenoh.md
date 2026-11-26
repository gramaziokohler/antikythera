# Running on Zenoh

[Zenoh](https://zenoh.io/) can carry Antikythera's messages and keep its state, like
[NATS](nats.md). Messages go between Zenoh sessions directly or through a router; state
goes into a *storage*: a router plugin that keeps the values put on a set of keys and
answers queries for them, on memory, RocksDB, the filesystem or other volumes.

Install the extra:

```bash
pip install "antikythera-sdk[deployment,zenoh]"
```

## The router

Antikythera keeps its state under `antikythera/storage`, so the router needs a storage
covering that prefix:

```json5
// zenoh.json5
{
  mode: "router",
  listen: { endpoints: ["tcp/0.0.0.0:7447"] },
  plugins: {
    storage_manager: {
      storages: {
        antikythera: { key_expr: "antikythera/storage/**", volume: { id: "memory" } },
      },
    },
  },
}
```

```bash
docker run -p 7447:7447 -v $PWD/zenoh.json5:/zenoh.json5 eclipse/zenoh:1.10.2 -c /zenoh.json5
```

The `memory` volume forgets everything when the router stops. For state that survives a
restart, use a persistent volume such as RocksDB or the filesystem; see the
[storage manager documentation](https://zenoh.io/docs/manual/plugin-storage-manager/).

Do not cover the whole `antikythera/**` prefix: messages are published on
`antikythera/task/...`, and a storage there would keep every one of them.

## The service

```bash
export ANTIKYTHERA_TRANSPORT=zenoh
export ANTIKYTHERA_STORAGE=zenoh
export ZENOH_CONNECT=tcp/localhost:7447
antikythera
```

| Variable | Default | |
| --- | --- | --- |
| `ANTIKYTHERA_TRANSPORT` | `mqtt` | `mqtt`, `nats` or `zenoh` |
| `ANTIKYTHERA_STORAGE` | `redis` | `redis`, `nats`, `zenoh` or `memory` |
| `ZENOH_CONNECT` | `tcp/127.0.0.1:7447` | Endpoint(s) to connect to, separated by commas |
| `ZENOH_MODE` | Zenoh's default, `peer` | `peer` or `client` |
| `ZENOH_CONFIG` | | A Zenoh JSON5 configuration file, for anything else (TLS, credentials, ...) |
| `ZENOH_STORAGE_PREFIX` | `antikythera/storage` | Key prefix of the stored state, so deployments can share a router |

As with NATS, transport and storage are independent: Zenoh messages with Redis storage
work as well.

## Actors

```bash
antikythera-actors run --transport zenoh --zenoh-connect tcp/localhost:7447
uvx --from "antikythera-sdk[zenoh]" antikythera-actors run --transport zenoh --actor my_actor.py
```

`ANTIKYTHERA_TRANSPORT` and the `ZENOH_*` variables set the defaults here too, and for
`antikythera_actors.run()`.

## From Python

```python
from compas_eve.codecs import ProtobufMessageCodec

from antikythera.transports.zenoh import ZenohTransport
from antikythera_orchestrator import Orchestrator
from antikythera_orchestrator.storage.zenoh_storage import ZenohStorage

orchestrator = Orchestrator(
    session,
    transport=ZenohTransport("tcp/localhost:7447", codec=ProtobufMessageCodec()),
    storage=ZenohStorage("tcp/localhost:7447"),
)
```

Both also take a `zenoh.Config`, built by hand or with
[zenoh_config][antikythera.transports.zenoh.zenoh_config].

## How it behaves

- **Peer to peer.** Messages do not need the router: sessions in `peer` mode find each
  other on the local network by multicast and talk directly. Only the storage needs a
  router.
- **Consistency.** Zenoh storages are eventually consistent: a query right after a write
  can return the previous value. The orchestrator reads its own writes, so `ZenohStorage`
  timestamps every write and waits until the storage answers with it, which costs a
  round trip per write. If no storage covers the prefix, writes fail after a timeout with a
  message saying so, instead of disappearing.
- **Late subscribers.** Zenoh announces subscriptions asynchronously, so a message sent
  the instant after an actor subscribes can miss it. The orchestrator re-sends unclaimed
  tasks, which covers this.
- **MQTT.** `ZenohTransport` maps topic names the way Zenoh's MQTT plugin does
  (`antikythera/task/+` is `antikythera/task/*`), so MQTT clients reaching a router through
  that plugin should exchange messages with it. This has not been tested, and neither has
  the web UI over Zenoh.

The Zenoh transport lives in Antikythera for now (`antikythera.transports.zenoh`).
compas_eve has a `ZenohTransport` too; this one gives every subscription its own Zenoh
subscriber, so removing one does not silence the others on its topic, maps MQTT-style
wildcards, and blocks rather than drops messages under congestion. It is meant to replace
compas_eve's once it has proven itself.
