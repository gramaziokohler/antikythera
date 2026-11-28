# Running on Zenoh

Like [NATS](nats.md), [Zenoh](https://zenoh.io/) can carry Antikythera's messages and
keep its data. Messages go from program to program directly, or through a Zenoh router.
Data goes into a *storage*: a part of the router that keeps values and answers questions
about them. A storage keeps its data in memory, in RocksDB, in files, or elsewhere.

Install the extra:

```bash
pip install "antikythera-sdk[deployment,zenoh]"
```

## The router

Antikythera keeps its data under the key `antikythera/storage`, so the router needs a
storage for that key:

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

The `memory` volume forgets everything when the router stops. To keep the data, use
RocksDB or the filesystem instead; see the
[storage manager documentation](https://zenoh.io/docs/manual/plugin-storage-manager/).

Do not use `antikythera/**` for the storage. Messages are sent on `antikythera/task/...`,
and the storage would keep every one of them.

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
| `ZENOH_STORAGE_PREFIX` | `antikythera/storage` | Key of the stored data, so several installations can share a router |

Transport and storage are separate choices: Zenoh for messages and Redis for data works
as well.

## Actors

```bash
antikythera-actors run --transport zenoh --zenoh-connect tcp/localhost:7447
uvx --from "antikythera-sdk[zenoh]" antikythera-actors run --transport zenoh --actor my_actor.py
```

`ANTIKYTHERA_TRANSPORT` and the `ZENOH_*` variables work here too, and in
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

- **No router needed for messages.** In `peer` mode, programs on the same network find
  each other and talk directly. Only the storage needs a router.
- **Writes wait.** Right after a write, a Zenoh storage can still return the old value for
  a short time. The orchestrator reads what it just wrote, so `ZenohStorage` waits after
  each write until the storage returns the new value. This takes about one network round
  trip. If no storage is set up for the key, writes fail after a timeout with a message
  that says so.
- **Messages right after subscribing.** Zenoh needs a moment to announce a new
  subscriber, so a message sent at that moment can be missed. The orchestrator sends
  unclaimed tasks again, so no task is lost.
- **MQTT.** Topic names match those of Zenoh's MQTT plugin (`antikythera/task/+` is
  `antikythera/task/*`), so MQTT clients connected through that plugin should work. This
  has not been tested, and neither has the web UI with Zenoh.

The Zenoh transport is part of Antikythera for now (`antikythera.transports.zenoh`).
compas_eve has a `ZenohTransport` too, but this one fixes three problems: removing one
subscriber there stops the others on the same topic, MQTT wildcards are not translated,
and messages are dropped when the network is busy. It will replace compas_eve's later.
