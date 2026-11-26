"""In-memory storage backend.

Keeps everything in dictionaries of the current process, so nothing outlives it. Use it
to run blueprints from Python code, in tests, or anywhere a Redis server is not worth
running.

Values are stored as COMPAS JSON and decoded on every read, like the Redis backend
does, so a caller never shares an object with the store and mutating a value it read
does not change what is stored.
"""

from __future__ import annotations

import datetime
import threading
from typing import Any
from typing import Optional

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


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class InMemoryStorage(StorageBackend):
    """Storage backend that keeps all state in memory.

    Every storage object it creates shares the same data, so an orchestrator and the
    code that set it up see the same blueprints and models.

    Examples
    --------
    >>> storage = InMemoryStorage()
    >>> with storage.model_storage() as models:
    ...     models.list_models()
    []
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # session_id -> {"session": str, "started_at": str, "ended_at": str | None}
        self._sessions: dict[str, dict[str, Any]] = {}
        # session_id -> blueprint_id -> key -> encoded value
        self._session_data: dict[str, dict[str, dict[str, str]]] = {}
        # blueprint_id -> (metadata, encoded blueprint), in upload order
        self._blueprints: dict[str, tuple[dict[str, Any], str]] = {}
        # model_id -> encoded model, in upload order
        self._models: dict[str, str] = {}
        self._nestings: dict[str, str] = {}

    def session_storage(self, session_id: str) -> InMemorySessionStorage:
        return InMemorySessionStorage(session_id, backend=self)

    def blueprint_storage(self) -> InMemoryBlueprintStorage:
        return InMemoryBlueprintStorage(backend=self)

    def model_storage(self) -> InMemoryModelStorage:
        return InMemoryModelStorage(backend=self)

    def list_sessions(self, limit: int = 10, offset: int = 0, newest_first: bool = True) -> list[str]:
        """IDs of the stored sessions, in the order they were first saved."""
        with self._lock:
            sessions = list(self._sessions)
        if newest_first:
            sessions.reverse()
        return sessions[offset : offset + limit]


class _InMemoryStorageBase:
    def __init__(self, backend: InMemoryStorage) -> None:
        self._backend = backend

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self) -> None:
        pass


class InMemorySessionStorage(_InMemoryStorageBase, BaseSessionStorage):
    """Session storage of an [InMemoryStorage][antikythera_orchestrator.storage.memory_storage.InMemoryStorage]."""

    def __init__(self, session_id: str, backend: Optional[InMemoryStorage] = None) -> None:
        super().__init__(backend or InMemoryStorage())
        self.session_id = session_id

    def list_sessions(self, limit: int = 10, offset: int = 0, newest_first: bool = True) -> list[str]:  # type: ignore[override]
        # Unlike the Redis backend this needs to know which store to list, so it is an
        # instance method rather than a static one.
        return self._backend.list_sessions(limit=limit, offset=offset, newest_first=newest_first)

    def _data(self, blueprint_id: str) -> dict[str, str]:
        return self._backend._session_data.setdefault(self.session_id, {}).setdefault(blueprint_id, {})

    def get(self, blueprint_id: str, key: str) -> Optional[Any]:
        with self._backend._lock:
            raw = self._data(blueprint_id).get(key)
        return None if raw is None else json_loads(raw)

    def set(self, blueprint_id: str, key: str, value: Any) -> None:
        encoded = json_dumps(value)
        with self._backend._lock:
            self._data(blueprint_id)[key] = encoded

    def set_all(self, blueprint_id: str, data: dict[str, Any]) -> None:
        encoded = {key: json_dumps(value) for key, value in data.items()}
        with self._backend._lock:
            self._data(blueprint_id).update(encoded)

    def get_all(self, blueprint_id: str) -> dict[str, Any]:
        with self._backend._lock:
            raw = dict(self._data(blueprint_id))
        return {key: json_loads(value) for key, value in raw.items()}

    def save_session(self, session: BlueprintSession) -> None:
        encoded = json_dumps(session)
        with self._backend._lock:
            existing = self._backend._sessions.get(self.session_id)
            self._backend._sessions[self.session_id] = {
                "session": encoded,
                "started_at": existing["started_at"] if existing else _now(),
                "ended_at": existing["ended_at"] if existing else None,
            }

    def load_session(self) -> Optional[BlueprintSession]:
        data = self.load_session_with_metadata()
        return data["session"] if data else None

    def load_session_with_metadata(self) -> Optional[dict]:
        with self._backend._lock:
            stored = self._backend._sessions.get(self.session_id)
            if stored is None:
                return None
            stored = dict(stored)
        stored["session"] = json_loads(stored["session"])
        return stored

    def remove_session(self) -> None:
        with self._backend._lock:
            if self.session_id not in self._backend._sessions:
                raise RequestedSessionNotFound(f"Session {self.session_id} not found")
            del self._backend._sessions[self.session_id]
            self._backend._session_data.pop(self.session_id, None)


class InMemoryBlueprintStorage(_InMemoryStorageBase, BaseBlueprintStorage):
    """Blueprint storage of an [InMemoryStorage][antikythera_orchestrator.storage.memory_storage.InMemoryStorage]."""

    def __init__(self, backend: Optional[InMemoryStorage] = None) -> None:
        super().__init__(backend or InMemoryStorage())

    def add_blueprint(self, blueprint: Blueprint) -> None:
        metadata = {
            "id": blueprint.id,
            "name": blueprint.name,
            "version": blueprint.version,
            "description": blueprint.description,
            "task_count": len(blueprint.tasks),
            "uploaded_at": _now(),
        }
        encoded = json_dumps(blueprint)
        with self._backend._lock:
            self._backend._blueprints[blueprint.id] = (metadata, encoded)

    def get_blueprint(self, blueprint_id: str) -> Blueprint:
        with self._backend._lock:
            stored = self._backend._blueprints.get(blueprint_id)
        if stored is None:
            raise RequestedBlueprintNotFound(f"Blueprint {blueprint_id} not found")
        return json_loads(stored[1])  # type: ignore[return-value]

    def list_blueprints(self) -> list[dict[str, Any]]:
        with self._backend._lock:
            return [dict(metadata) for metadata, _ in self._backend._blueprints.values()]

    def remove_blueprint(self, blueprint_id: str) -> None:
        with self._backend._lock:
            if self._backend._blueprints.pop(blueprint_id, None) is None:
                raise RequestedBlueprintNotFound(f"Blueprint {blueprint_id} not found")


class InMemoryModelStorage(_InMemoryStorageBase, BaseModelStorage):
    """Model storage of an [InMemoryStorage][antikythera_orchestrator.storage.memory_storage.InMemoryStorage]."""

    def __init__(self, backend: Optional[InMemoryStorage] = None) -> None:
        super().__init__(backend or InMemoryStorage())

    def add_model(self, model_id: str, model: Any) -> None:
        encoded = json_dumps(model)
        with self._backend._lock:
            self._backend._models[model_id] = encoded

    def add_nesting(self, model_id: str, nesting: Any) -> None:
        encoded = json_dumps(nesting)
        with self._backend._lock:
            if model_id not in self._backend._models:
                raise RequestedModelNotFound(f"Model {model_id} not found")
            self._backend._nestings[model_id] = encoded

    def get_nesting(self, model_id: str) -> Optional[Any]:
        with self._backend._lock:
            raw = self._backend._nestings.get(model_id)
        return None if raw is None else json_loads(raw)

    def get_model(self, model_id: str) -> Any:
        with self._backend._lock:
            raw = self._backend._models.get(model_id)
        if raw is None:
            raise RequestedModelNotFound(f"Model {model_id} not found")
        return json_loads(raw)

    def list_models(self) -> list[str]:
        with self._backend._lock:
            return list(self._backend._models)

    def remove_model(self, model_id: str) -> None:
        with self._backend._lock:
            if self._backend._models.pop(model_id, None) is None:
                raise RequestedModelNotFound(f"Model {model_id} not found")
            self._backend._nestings.pop(model_id, None)
