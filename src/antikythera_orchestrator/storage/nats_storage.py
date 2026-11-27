"""Storage backend on NATS JetStream.

Everything is kept in JetStream object stores, which hold values of any size, so large
models and task outputs such as robot trajectories fit as well as small values. Four
buckets are used, named after a prefix (``antikythera`` by default):

* ``<prefix>-sessions``: one object per session, named after its id.
* ``<prefix>-session-data``: the data of a session, one object per session and blueprint
  (``<session id>/<blueprint id>``) holding all of its keys, so reading it whole is one get.
* ``<prefix>-blueprints``: one object per blueprint, its metadata in the object description.
* ``<prefix>-models``: models, and nesting results under ``nesting/<model id>``.

Combined with the NATS transport this runs Antikythera on a NATS server alone, with
JetStream enabled (``nats-server -js``).
"""

from __future__ import annotations

import datetime
import json
import threading
from typing import Any
from typing import List
from typing import Optional
from typing import Union

from compas.data import json_dumps
from compas.data import json_loads

from antikythera.models import Blueprint
from antikythera.models import BlueprintSession
from antikythera.transports.nats import DEFAULT_SERVERS
from antikythera.transports.nats import AsyncioThread
from antikythera_orchestrator.storage.backends import StorageBackend
from antikythera_orchestrator.storage.exceptions import RequestedBlueprintNotFound
from antikythera_orchestrator.storage.exceptions import RequestedModelNotFound
from antikythera_orchestrator.storage.exceptions import RequestedSessionNotFound
from antikythera_orchestrator.storage.interfaces import BaseBlueprintStorage
from antikythera_orchestrator.storage.interfaces import BaseModelStorage
from antikythera_orchestrator.storage.interfaces import BaseSessionStorage

try:
    import nats
    from nats.js.api import ObjectMeta
    from nats.js.errors import NotFoundError
    from nats.js.errors import ObjectNotFoundError
except ImportError as e:  # pragma: no cover
    raise ImportError("The NATS storage backend needs nats-py: pip install 'antikythera-sdk[nats]'") from e

_TIMEOUT = 30
_NESTING_PREFIX = "nesting/"


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class NatsStorage(StorageBackend):
    """Storage backend that keeps sessions, blueprints and models in NATS JetStream.

    The connection is opened on first use and shared by every storage object this
    backend creates. Call [close][antikythera_orchestrator.storage.nats_storage.NatsStorage.close]
    when done with it.

    Parameters
    ----------
    servers : str or list of str, optional
        URL(s) of the NATS server(s), which must have JetStream enabled.
    prefix : str, optional
        Prefix of the object store bucket names, so several deployments can share a server.
    **connect_options
        Further keyword arguments for ``nats.connect``, e.g. ``user_credentials`` or ``tls``.
    """

    def __init__(self, servers: Union[str, List[str]] = DEFAULT_SERVERS, prefix: str = "antikythera", **connect_options: Any) -> None:
        self.servers = servers
        self.prefix = prefix
        self._connect_options = connect_options
        self._connect_lock = threading.Lock()
        self._loop: Optional[AsyncioThread] = None
        self._client = None
        self._stores = {}
        # Session data documents are read, changed and written back; this keeps writers in
        # this process from overwriting each other's keys.
        self.data_lock = threading.RLock()

    # -- connection ----------------------------------------------------------------------

    def _connect(self) -> None:
        with self._connect_lock:
            if self._client is not None:
                return
            loop = AsyncioThread(name="nats-storage")

            async def connect():
                client = await nats.connect(self.servers, **self._connect_options)
                js = client.jetstream()
                stores = {}
                for kind in ("sessions", "session-data", "blueprints", "models"):
                    stores[kind] = await js.create_object_store(f"{self.prefix}-{kind}")
                return client, stores

            try:
                self._client, self._stores = loop.run(connect(), timeout=_TIMEOUT)
            except Exception:
                loop.stop()
                raise
            self._loop = loop

    def run(self, coroutine_factory) -> Any:
        """Run ``coroutine_factory(stores)`` on the connection's event loop and return its result."""
        self._connect()
        return self._loop.run(coroutine_factory(self._stores), timeout=_TIMEOUT)

    def close(self) -> None:
        """Close the connection to NATS."""
        with self._connect_lock:
            if self._client is None:
                return
            try:
                self._loop.run(self._client.drain(), timeout=10)
            finally:
                self._loop.stop()
                self._client, self._loop, self._stores = None, None, {}

    # -- object helpers --------------------------------------------------------------------

    def get(self, kind: str, name: str) -> Optional[bytes]:
        async def get(stores):
            try:
                return (await stores[kind].get(name)).data
            except ObjectNotFoundError:
                return None

        return self.run(get)

    def get_with_description(self, kind: str, name: str) -> Optional[tuple]:
        async def get(stores):
            try:
                result = await stores[kind].get(name)
            except ObjectNotFoundError:
                return None
            return result.data, result.info.description

        return self.run(get)

    def put(self, kind: str, name: str, data: str, description: Optional[str] = None) -> None:
        async def put(stores):
            await stores[kind].put(name, data.encode("utf-8"), meta=ObjectMeta(name=name, description=description))

        self.run(put)

    def delete(self, kind: str, name: str) -> bool:
        async def delete(stores):
            try:
                await stores[kind].delete(name)
                return True
            except ObjectNotFoundError:
                return False

        return self.run(delete)

    def list(self, kind: str) -> list:
        """Info of the live objects of a bucket: name, description and modification time."""

        async def list_objects(stores):
            try:
                return await stores[kind].list(ignore_deletes=True)
            except NotFoundError:
                return []

        return self.run(list_objects)

    # -- StorageBackend ----------------------------------------------------------------------

    def session_storage(self, session_id: str) -> NatsSessionStorage:
        return NatsSessionStorage(session_id, backend=self)

    def blueprint_storage(self) -> NatsBlueprintStorage:
        return NatsBlueprintStorage(backend=self)

    def model_storage(self) -> NatsModelStorage:
        return NatsModelStorage(backend=self)

    def list_sessions(self, limit: int = 10, offset: int = 0, newest_first: bool = True) -> list[str]:
        # The description of a session object holds the time it was first saved.
        infos = sorted(self.list("sessions"), key=lambda info: info.description or "")
        sessions = [info.name for info in infos]
        if newest_first:
            sessions.reverse()
        return sessions[offset : offset + limit]


class _NatsStorageBase:
    def __init__(self, backend: NatsStorage) -> None:
        self._backend = backend

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self) -> None:
        # The connection belongs to the backend and is shared; nothing to release here.
        pass


class NatsSessionStorage(_NatsStorageBase, BaseSessionStorage):
    """Session storage of a [NatsStorage][antikythera_orchestrator.storage.nats_storage.NatsStorage]."""

    def __init__(self, session_id: str, backend: Optional[NatsStorage] = None) -> None:
        super().__init__(backend or NatsStorage())
        self.session_id = session_id

    def list_sessions(self, limit: int = 10, offset: int = 0, newest_first: bool = True) -> list[str]:  # type: ignore[override]
        return self._backend.list_sessions(limit=limit, offset=offset, newest_first=newest_first)

    def _data_name(self, blueprint_id: str) -> str:
        return f"{self.session_id}/{blueprint_id}"

    def _read_data(self, blueprint_id: str) -> dict:
        raw = self._backend.get("session-data", self._data_name(blueprint_id))
        return json.loads(raw) if raw else {}

    def _write_data(self, blueprint_id: str, data: dict) -> None:
        self._backend.put("session-data", self._data_name(blueprint_id), json.dumps(data))

    def get(self, blueprint_id: str, key: str) -> Optional[Any]:
        raw = self._read_data(blueprint_id).get(key)
        return None if raw is None else json_loads(raw)

    def set(self, blueprint_id: str, key: str, value: Any) -> None:
        self.set_all(blueprint_id, {key: value})

    def set_all(self, blueprint_id: str, data: dict[str, Any]) -> None:
        encoded = {key: json_dumps(value) for key, value in data.items()}
        with self._backend.data_lock:
            stored = self._read_data(blueprint_id)
            stored.update(encoded)
            self._write_data(blueprint_id, stored)

    def get_all(self, blueprint_id: str) -> dict[str, Any]:
        return {key: json_loads(value) for key, value in self._read_data(blueprint_id).items()}

    def save_session(self, session: BlueprintSession) -> None:
        stored = self._backend.get_with_description("sessions", self.session_id)
        if stored:
            previous = json_loads(stored[0].decode("utf-8"))
            started_at, ended_at = previous.get("started_at"), previous.get("ended_at")
        else:
            started_at, ended_at = _now(), None
        value = {"session": session, "started_at": started_at, "ended_at": ended_at}
        self._backend.put("sessions", self.session_id, json_dumps(value), description=started_at)

    def load_session(self) -> Optional[BlueprintSession]:
        data = self.load_session_with_metadata()
        return data.get("session") if data else None

    def load_session_with_metadata(self) -> Optional[dict]:
        raw = self._backend.get("sessions", self.session_id)
        return None if raw is None else json_loads(raw.decode("utf-8"))

    def remove_session(self) -> None:
        if not self._backend.delete("sessions", self.session_id):
            raise RequestedSessionNotFound(f"Session {self.session_id} not found")
        prefix = f"{self.session_id}/"
        with self._backend.data_lock:
            for info in self._backend.list("session-data"):
                if info.name.startswith(prefix):
                    self._backend.delete("session-data", info.name)


class NatsBlueprintStorage(_NatsStorageBase, BaseBlueprintStorage):
    """Blueprint storage of a [NatsStorage][antikythera_orchestrator.storage.nats_storage.NatsStorage]."""

    def __init__(self, backend: Optional[NatsStorage] = None) -> None:
        super().__init__(backend or NatsStorage())

    def add_blueprint(self, blueprint: Blueprint) -> None:
        metadata = {
            "id": blueprint.id,
            "name": blueprint.name,
            "version": blueprint.version,
            "description": blueprint.description,
            "task_count": len(blueprint.tasks),
            "uploaded_at": _now(),
        }
        self._backend.put("blueprints", blueprint.id, json_dumps(blueprint), description=json.dumps(metadata))

    def get_blueprint(self, blueprint_id: str) -> Blueprint:
        raw = self._backend.get("blueprints", blueprint_id)
        if raw is None:
            raise RequestedBlueprintNotFound(f"Blueprint {blueprint_id} not found")
        return json_loads(raw.decode("utf-8"))  # type: ignore[return-value]

    def list_blueprints(self) -> list[dict[str, Any]]:
        metadata = [json.loads(info.description) for info in self._backend.list("blueprints") if info.description]
        return sorted(metadata, key=lambda item: item.get("uploaded_at") or "")

    def remove_blueprint(self, blueprint_id: str) -> None:
        if not self._backend.delete("blueprints", blueprint_id):
            raise RequestedBlueprintNotFound(f"Blueprint {blueprint_id} not found")


class NatsModelStorage(_NatsStorageBase, BaseModelStorage):
    """Model storage of a [NatsStorage][antikythera_orchestrator.storage.nats_storage.NatsStorage]."""

    def __init__(self, backend: Optional[NatsStorage] = None) -> None:
        super().__init__(backend or NatsStorage())

    def add_model(self, model_id: str, model: Any) -> None:
        # Keep the time it was first added, so models list in upload order.
        stored = self._backend.get_with_description("models", model_id)
        added_at = stored[1] if stored and stored[1] else _now()
        self._backend.put("models", model_id, json_dumps(model), description=added_at)

    def add_nesting(self, model_id: str, nesting: Any) -> None:
        if self._backend.get("models", model_id) is None:
            raise RequestedModelNotFound(f"Model {model_id} not found")
        self._backend.put("models", _NESTING_PREFIX + model_id, json_dumps(nesting))

    def get_nesting(self, model_id: str) -> Optional[Any]:
        raw = self._backend.get("models", _NESTING_PREFIX + model_id)
        return None if raw is None else json_loads(raw.decode("utf-8"))

    def get_model(self, model_id: str) -> Any:
        raw = self._backend.get("models", model_id)
        if raw is None:
            raise RequestedModelNotFound(f"Model {model_id} not found")
        return json_loads(raw.decode("utf-8"))

    def list_models(self) -> list[str]:
        infos = [info for info in self._backend.list("models") if not info.name.startswith(_NESTING_PREFIX)]
        return [info.name for info in sorted(infos, key=lambda info: info.description or "")]

    def remove_model(self, model_id: str) -> None:
        if not self._backend.delete("models", model_id):
            raise RequestedModelNotFound(f"Model {model_id} not found")
        self._backend.delete("models", _NESTING_PREFIX + model_id)
