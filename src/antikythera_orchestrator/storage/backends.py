"""Storage backends.

A storage backend hands out the three storage objects the orchestrator needs: one for
the data of a session, one for blueprints and one for models. Pass a backend to
[Orchestrator][antikythera_orchestrator.orchestrator.Orchestrator] to choose where its
state lives; by default it is the one configured by ``ANTIKYTHERA_STORAGE``, Redis unless set.
"""

from __future__ import annotations

import threading
from abc import ABC
from abc import abstractmethod
from typing import Optional

from antikythera_orchestrator.storage.interfaces import BaseBlueprintStorage
from antikythera_orchestrator.storage.interfaces import BaseModelStorage
from antikythera_orchestrator.storage.interfaces import BaseSessionStorage


class StorageBackend(ABC):
    """Creates the session, blueprint and model storage objects of one backend."""

    @abstractmethod
    def session_storage(self, session_id: str) -> BaseSessionStorage:
        """Storage for the data and state of the session ``session_id``."""

    @abstractmethod
    def blueprint_storage(self) -> BaseBlueprintStorage:
        """Storage for uploaded blueprints, including the inner blueprints of composite tasks."""

    @abstractmethod
    def model_storage(self) -> BaseModelStorage:
        """Storage for models and their nesting results, read by sequencers."""

    @abstractmethod
    def list_sessions(self, limit: int = 10, offset: int = 0, newest_first: bool = True) -> list[str]:
        """IDs of the stored sessions, by default the most recently started first."""


class RedisStorage(StorageBackend):
    """Persistent storage in Redis, configured by ``REDIS_HOST`` and ``REDIS_PORT``.

    This is the default backend.
    """

    def session_storage(self, session_id: str) -> BaseSessionStorage:
        from antikythera_orchestrator.storage.redis_storage import SessionStorage

        return SessionStorage(session_id)

    def blueprint_storage(self) -> BaseBlueprintStorage:
        from antikythera_orchestrator.storage.redis_storage import BlueprintStorage

        return BlueprintStorage()

    def model_storage(self) -> BaseModelStorage:
        from antikythera_orchestrator.storage.redis_storage import ModelStorage

        return ModelStorage()

    def list_sessions(self, limit: int = 10, offset: int = 0, newest_first: bool = True) -> list[str]:
        from antikythera_orchestrator.storage.redis_storage import SessionStorage

        return SessionStorage.list_sessions(limit=limit, offset=offset, newest_first=newest_first)


_DEFAULT_STORAGE: Optional[StorageBackend] = None
_DEFAULT_STORAGE_LOCK = threading.Lock()


def default_storage() -> StorageBackend:
    """The storage backend configured by ``ANTIKYTHERA_STORAGE``, created once per process.

    ``"redis"`` (the default) is [RedisStorage][antikythera_orchestrator.storage.backends.RedisStorage],
    ``"nats"`` a [NatsStorage][antikythera_orchestrator.storage.nats_storage.NatsStorage] at
    ``NATS_URL``, ``"zenoh"`` a [ZenohStorage][antikythera_orchestrator.storage.zenoh_storage.ZenohStorage]
    configured by ``ZENOH_CONNECT``, and ``"memory"`` an [InMemoryStorage][antikythera_orchestrator.storage.memory_storage.InMemoryStorage],
    which forgets everything when the process ends.
    """
    global _DEFAULT_STORAGE
    with _DEFAULT_STORAGE_LOCK:
        if _DEFAULT_STORAGE is None:
            _DEFAULT_STORAGE = create_storage()
        return _DEFAULT_STORAGE


def create_storage(kind: Optional[str] = None) -> StorageBackend:
    """Create a storage backend: ``"redis"``, ``"nats"``, ``"zenoh"`` or ``"memory"``. Defaults to ``ANTIKYTHERA_STORAGE``."""
    from antikythera import config

    kind = (kind or config.STORAGE).lower()
    if kind == "redis":
        return RedisStorage()
    if kind == "nats":
        from antikythera_orchestrator.storage.nats_storage import NatsStorage

        return NatsStorage(config.NATS_URL, prefix=config.NATS_STORAGE_PREFIX)
    if kind == "zenoh":
        from antikythera.transport import configured_zenoh
        from antikythera_orchestrator.storage.zenoh_storage import ZenohStorage

        return ZenohStorage(configured_zenoh(), prefix=config.ZENOH_STORAGE_PREFIX)
    if kind == "memory":
        from antikythera_orchestrator.storage.memory_storage import InMemoryStorage

        return InMemoryStorage()
    raise ValueError(f"Unknown storage '{kind}': use 'redis', 'nats', 'zenoh' or 'memory'")
