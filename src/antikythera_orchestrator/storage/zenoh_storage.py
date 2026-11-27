"""Storage backend on Zenoh storages.

A Zenoh storage keeps the values put on the keys it covers and answers queries for them.
Storages run in a Zenoh router (``zenohd``), on memory, RocksDB, the filesystem or another
volume, and several can replicate each other. This backend keeps everything under one key
prefix (``antikythera/storage`` by default), which a storage on the router must cover:

* ``<prefix>/sessions/<session id>``: a session with its start and end times.
* ``<prefix>/session-data/<session id>/<blueprint id>/<key>``: one value of a session's data.
* ``<prefix>/blueprints/<id>`` and ``<prefix>/blueprint-info/<id>``: a blueprint, and the
  summary listed for it.
* ``<prefix>/models/<id>``, ``<prefix>/model-info/<id>`` and ``<prefix>/nestings/<id>``: a
  model, when it was added, and its nesting result.

Zenoh storages are eventually consistent: a query right after a put may still be answered
with the previous value. The orchestrator reads its own writes all the time, so every write
here is timestamped and waits until the storage answers with it, or something newer.

Keep the prefix apart from the topics messages are published on (``antikythera/task/...``):
a storage covering them would keep every message.
"""

from __future__ import annotations

import datetime
import json
import threading
import time
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from typing import Union
from urllib.parse import unquote

from compas.data import json_dumps
from compas.data import json_loads

from antikythera.models import Blueprint
from antikythera.models import BlueprintSession
from antikythera_orchestrator.storage.backends import StorageBackend
from antikythera_orchestrator.storage.exceptions import RequestedBlueprintNotFound
from antikythera_orchestrator.storage.exceptions import RequestedModelNotFound
from antikythera_orchestrator.storage.exceptions import RequestedSessionNotFound
from antikythera_orchestrator.storage.interfaces import BaseBlueprintStorage
from antikythera_orchestrator.storage.interfaces import BaseModelStorage
from antikythera_orchestrator.storage.interfaces import BaseSessionStorage

try:
    import zenoh

    from antikythera.transports.zenoh import DEFAULT_ENDPOINTS
    from antikythera.transports.zenoh import zenoh_config
except ImportError as e:  # pragma: no cover
    raise ImportError("The Zenoh storage backend needs eclipse-zenoh: pip install 'antikythera-sdk[zenoh]'") from e

DEFAULT_PREFIX = "antikythera/storage"

# Characters that cannot appear in a key expression chunk, or would split one.
_RESERVED = "%/*$?#"


def _escape(chunk: str) -> str:
    """Make ``chunk`` usable as one chunk of a key expression, reversibly."""
    if chunk == "":
        return "%"
    return "".join(f"%{ord(c):02X}" if c in _RESERVED else c for c in chunk)


def _unescape(chunk: str) -> str:
    return "" if chunk == "%" else unquote(chunk)


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class StorageTimeout(RuntimeError):
    """A Zenoh storage did not confirm a write in time."""


class ZenohStorage(StorageBackend):
    """Storage backend that keeps sessions, blueprints and models in Zenoh storages.

    The Zenoh session is opened on first use and shared by every storage object this backend
    creates. Call [close][antikythera_orchestrator.storage.zenoh_storage.ZenohStorage.close]
    when done with it.

    Parameters
    ----------
    config : zenoh.Config or str or list of str, optional
        A Zenoh configuration, or the endpoint(s) of the router(s) holding the storage.
        Defaults to ``tcp/127.0.0.1:7447``.
    prefix : str, optional
        Key prefix of everything stored, covered by a storage on the router. Defaults to
        ``antikythera/storage``; use another one for deployments sharing a router.
    timeout : float, optional
        Seconds to wait for the storage to answer a query or confirm a write.
    """

    def __init__(self, config: Optional[Union["zenoh.Config", str, List[str]]] = None, prefix: str = DEFAULT_PREFIX, timeout: float = 10.0) -> None:
        self.config = config
        self.prefix = prefix.strip("/")
        self.timeout = timeout
        self._open_lock = threading.Lock()
        self._session = None

    # -- connection ----------------------------------------------------------------------

    @property
    def session(self) -> "zenoh.Session":
        with self._open_lock:
            if self._session is None:
                config = self.config
                if config is None or isinstance(config, (str, list)):
                    config = zenoh_config(connect=config or DEFAULT_ENDPOINTS)
                self._session = zenoh.open(config)
            return self._session

    def close(self) -> None:
        """Close the Zenoh session."""
        with self._open_lock:
            if self._session is not None:
                self._session.close()
                self._session = None

    # -- key-value helpers -----------------------------------------------------------------

    def key(self, *chunks: str) -> str:
        """The key of ``chunks`` (a kind followed by ids) under the prefix, ids escaped."""
        kind, *ids = chunks
        return "/".join([self.prefix, kind, *(_escape(chunk) for chunk in ids)])

    def _query(self, selector: str) -> Dict[str, Tuple[bytes, Any]]:
        """The newest value and timestamp of every stored key matching ``selector``."""
        found: Dict[str, Tuple[bytes, Any]] = {}
        replies = self.session.get(selector, consolidation=zenoh.ConsolidationMode.LATEST, timeout=self.timeout)
        for reply in replies:
            sample = reply.ok
            if sample is None:
                continue
            key = str(sample.key_expr)
            previous = found.get(key)
            if previous is None or (sample.timestamp is not None and previous[1] is not None and sample.timestamp > previous[1]):
                found[key] = (sample.payload.to_bytes(), sample.timestamp)
        return found

    def get(self, key: str) -> Optional[bytes]:
        found = self._query(key).get(key)
        return None if found is None else found[0]

    def get_matching(self, *chunks: str) -> Dict[str, bytes]:
        """Values of the keys one level below ``chunks``, by their last (unescaped) chunk."""
        selector = self.key(*chunks) + "/*"
        return {_unescape(key.rsplit("/", 1)[1]): value for key, (value, _) in self._query(selector).items()}

    def put_all(self, values: Dict[str, str]) -> None:
        """Put each value on its key, and wait until the storage answers with all of them."""
        stamps = {}
        for key, value in values.items():
            stamps[key] = self.session.new_timestamp()
            self.session.put(key, value.encode("utf-8"), timestamp=stamps[key])
        self._confirm(stamps, deleted=False)

    def put(self, key: str, value: str) -> None:
        self.put_all({key: value})

    def delete_all(self, keys: List[str]) -> None:
        """Delete the keys, and wait until the storage no longer answers with them."""
        stamps = {}
        for key in keys:
            stamps[key] = self.session.new_timestamp()
            self.session.delete(key, timestamp=stamps[key])
        self._confirm(stamps, deleted=True)

    def _confirm(self, stamps: Dict[str, Any], deleted: bool) -> None:
        deadline = time.monotonic() + self.timeout
        pending = dict(stamps)
        while pending:
            for key in list(pending):
                found = self._query(key).get(key)
                if deleted:
                    done = found is None or (found[1] is not None and found[1] > pending[key])
                else:
                    done = found is not None and found[1] is not None and found[1] >= pending[key]
                if done:
                    del pending[key]
            if not pending:
                return
            if time.monotonic() > deadline:
                raise StorageTimeout(
                    f"No Zenoh storage confirmed the write of {sorted(pending)[0]} within {self.timeout}s. Is a storage covering '{self.prefix}/**' configured on the router?"
                )
            time.sleep(0.002)

    # -- StorageBackend ----------------------------------------------------------------------

    def session_storage(self, session_id: str) -> ZenohSessionStorage:
        return ZenohSessionStorage(session_id, backend=self)

    def blueprint_storage(self) -> ZenohBlueprintStorage:
        return ZenohBlueprintStorage(backend=self)

    def model_storage(self) -> ZenohModelStorage:
        return ZenohModelStorage(backend=self)

    def list_sessions(self, limit: int = 10, offset: int = 0, newest_first: bool = True) -> list[str]:
        started = {session_id: json.loads(raw).get("started_at") or "" for session_id, raw in self.get_matching("sessions").items()}
        sessions = sorted(started, key=lambda session_id: started[session_id])
        if newest_first:
            sessions.reverse()
        return sessions[offset : offset + limit]


class _ZenohStorageBase:
    def __init__(self, backend: ZenohStorage) -> None:
        self._backend = backend

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self) -> None:
        # The Zenoh session belongs to the backend and is shared; nothing to release here.
        pass


class ZenohSessionStorage(_ZenohStorageBase, BaseSessionStorage):
    """Session storage of a [ZenohStorage][antikythera_orchestrator.storage.zenoh_storage.ZenohStorage]."""

    def __init__(self, session_id: str, backend: Optional[ZenohStorage] = None) -> None:
        super().__init__(backend or ZenohStorage())
        self.session_id = session_id

    def list_sessions(self, limit: int = 10, offset: int = 0, newest_first: bool = True) -> list[str]:  # type: ignore[override]
        return self._backend.list_sessions(limit=limit, offset=offset, newest_first=newest_first)

    def get(self, blueprint_id: str, key: str) -> Optional[Any]:
        raw = self._backend.get(self._backend.key("session-data", self.session_id, blueprint_id, key))
        return None if raw is None else json_loads(raw.decode("utf-8"))

    def set(self, blueprint_id: str, key: str, value: Any) -> None:
        self.set_all(blueprint_id, {key: value})

    def set_all(self, blueprint_id: str, data: dict[str, Any]) -> None:
        # One key per value, so writers never overwrite each other's keys.
        self._backend.put_all({self._backend.key("session-data", self.session_id, blueprint_id, key): json_dumps(value) for key, value in data.items()})

    def get_all(self, blueprint_id: str) -> dict[str, Any]:
        stored = self._backend.get_matching("session-data", self.session_id, blueprint_id)
        return {key: json_loads(raw.decode("utf-8")) for key, raw in stored.items()}

    def save_session(self, session: BlueprintSession) -> None:
        previous = self.load_session_with_metadata()
        if previous:
            started_at, ended_at = previous.get("started_at"), previous.get("ended_at")
        else:
            started_at, ended_at = _now(), None
        value = {"session": session, "started_at": started_at, "ended_at": ended_at}
        self._backend.put(self._backend.key("sessions", self.session_id), json_dumps(value))

    def load_session(self) -> Optional[BlueprintSession]:
        data = self.load_session_with_metadata()
        return data.get("session") if data else None

    def load_session_with_metadata(self) -> Optional[dict]:
        raw = self._backend.get(self._backend.key("sessions", self.session_id))
        return None if raw is None else json_loads(raw.decode("utf-8"))

    def remove_session(self) -> None:
        session_key = self._backend.key("sessions", self.session_id)
        if self._backend.get(session_key) is None:
            raise RequestedSessionNotFound(f"Session {self.session_id} not found")
        # Each key is deleted on its own: a put right after a wildcard delete can be lost.
        data_keys = list(self._backend._query(self._backend.key("session-data", self.session_id) + "/**"))
        self._backend.delete_all([session_key, *data_keys])


class ZenohBlueprintStorage(_ZenohStorageBase, BaseBlueprintStorage):
    """Blueprint storage of a [ZenohStorage][antikythera_orchestrator.storage.zenoh_storage.ZenohStorage]."""

    def __init__(self, backend: Optional[ZenohStorage] = None) -> None:
        super().__init__(backend or ZenohStorage())

    def add_blueprint(self, blueprint: Blueprint) -> None:
        info = {
            "id": blueprint.id,
            "name": blueprint.name,
            "version": blueprint.version,
            "description": blueprint.description,
            "task_count": len(blueprint.tasks),
            "uploaded_at": _now(),
        }
        self._backend.put_all(
            {
                self._backend.key("blueprints", blueprint.id): json_dumps(blueprint),
                self._backend.key("blueprint-info", blueprint.id): json.dumps(info),
            }
        )

    def get_blueprint(self, blueprint_id: str) -> Blueprint:
        raw = self._backend.get(self._backend.key("blueprints", blueprint_id))
        if raw is None:
            raise RequestedBlueprintNotFound(f"Blueprint {blueprint_id} not found")
        return json_loads(raw.decode("utf-8"))  # type: ignore[return-value]

    def list_blueprints(self) -> list[dict[str, Any]]:
        infos = [json.loads(raw) for raw in self._backend.get_matching("blueprint-info").values()]
        return sorted(infos, key=lambda item: item.get("uploaded_at") or "")

    def remove_blueprint(self, blueprint_id: str) -> None:
        key = self._backend.key("blueprints", blueprint_id)
        if self._backend.get(key) is None:
            raise RequestedBlueprintNotFound(f"Blueprint {blueprint_id} not found")
        self._backend.delete_all([key, self._backend.key("blueprint-info", blueprint_id)])


class ZenohModelStorage(_ZenohStorageBase, BaseModelStorage):
    """Model storage of a [ZenohStorage][antikythera_orchestrator.storage.zenoh_storage.ZenohStorage]."""

    def __init__(self, backend: Optional[ZenohStorage] = None) -> None:
        super().__init__(backend or ZenohStorage())

    def add_model(self, model_id: str, model: Any) -> None:
        # Keep the time it was first added, so models list in upload order.
        info_key = self._backend.key("model-info", model_id)
        added_at = self._backend.get(info_key)
        self._backend.put_all(
            {
                self._backend.key("models", model_id): json_dumps(model),
                info_key: added_at.decode("utf-8") if added_at else _now(),
            }
        )

    def add_nesting(self, model_id: str, nesting: Any) -> None:
        if self._backend.get(self._backend.key("model-info", model_id)) is None:
            raise RequestedModelNotFound(f"Model {model_id} not found")
        self._backend.put(self._backend.key("nestings", model_id), json_dumps(nesting))

    def get_nesting(self, model_id: str) -> Optional[Any]:
        raw = self._backend.get(self._backend.key("nestings", model_id))
        return None if raw is None else json_loads(raw.decode("utf-8"))

    def get_model(self, model_id: str) -> Any:
        raw = self._backend.get(self._backend.key("models", model_id))
        if raw is None:
            raise RequestedModelNotFound(f"Model {model_id} not found")
        return json_loads(raw.decode("utf-8"))

    def list_models(self) -> list[str]:
        added = {model_id: raw.decode("utf-8") for model_id, raw in self._backend.get_matching("model-info").items()}
        return sorted(added, key=lambda model_id: added[model_id])

    def remove_model(self, model_id: str) -> None:
        info_key = self._backend.key("model-info", model_id)
        if self._backend.get(info_key) is None:
            raise RequestedModelNotFound(f"Model {model_id} not found")
        self._backend.delete_all([self._backend.key("models", model_id), info_key, self._backend.key("nestings", model_id)])
