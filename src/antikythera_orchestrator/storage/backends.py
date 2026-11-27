"""Storage backends.

A storage backend hands out the three storage objects the orchestrator needs: one for
the data of a session, one for blueprints and one for models. Pass a backend to
[Orchestrator][antikythera_orchestrator.orchestrator.Orchestrator] to choose where its
state lives; by default it is Redis.
"""

from __future__ import annotations

from abc import ABC
from abc import abstractmethod

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


class RedisStorage(StorageBackend):
    """Persistent storage in Redis, configured by ``REDIS_HOST`` and ``REDIS_PORT``.

    This is the default backend, and the one the HTTP API service uses.
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
