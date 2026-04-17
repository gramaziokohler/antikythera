import datetime
import logging
from typing import Any
from typing import Optional
from typing import cast

import redis
from compas.data import json_dumps
from compas.data import json_loads

from antikythera import config
from antikythera.models import Blueprint
from antikythera.models import BlueprintSession
from antikythera_orchestrator.storage.exceptions import RequestedBlueprintNotFound
from antikythera_orchestrator.storage.exceptions import RequestedModelNotFound
from antikythera_orchestrator.storage.exceptions import RequestedSessionNotFound
from antikythera_orchestrator.storage.interfaces import BaseBlueprintStorage
from antikythera_orchestrator.storage.interfaces import BaseModelStorage
from antikythera_orchestrator.storage.interfaces import BaseSessionStorage

LOG = logging.getLogger(__name__)

# Each storage class uses a separate Redis logical database to mirror the immudb
# per-database namespace separation.
_SESSION_DB = 0
_BLUEPRINT_DB = 1
_MODEL_DB = 2


def _create_redis_client(db: int) -> redis.Redis:
    try:
        client = redis.Redis(
            host=config.REDIS_HOST,
            port=config.REDIS_PORT,
            db=db,
            decode_responses=False,
        )
        client.ping()
        return client
    except Exception as e:
        LOG.exception(f"Failed to connect to Redis: {e}")
        raise


def _update_index(client: redis.Redis, index_key: str, items_to_add: list[str] = None, items_to_remove: list[str] = None) -> str:
    """Read the JSON-encoded index list from *index_key*, apply mutations, and
    return the new serialised value without writing it back (allows batching via
    a pipeline)."""
    items_to_add = items_to_add or []
    items_to_remove = items_to_remove or []

    raw = client.get(index_key)
    if raw:
        index_data = json_loads(raw.decode())
        index_data = cast(list[str], index_data)
    else:
        index_data = []

    index_data.extend(items_to_add)
    index_data = list(dict.fromkeys(index_data))  # Remove duplicates

    for item_to_remove in items_to_remove:
        try:
            index_data.remove(item_to_remove)
        except ValueError:
            pass  # Item not in list, ignore

    return json_dumps(index_data)


class SessionStorage(BaseSessionStorage):
    _DB = _SESSION_DB

    def __init__(self, session_id: str):
        self.client = _create_redis_client(self._DB)
        self.session_id = session_id

    @staticmethod
    def list_sessions(limit: int = 10, offset: int = 0, newest_first: bool = True) -> list[str]:
        client = _create_redis_client(SessionStorage._DB)
        try:
            raw = client.get("session:index")
            if not raw:
                return []
            all_sessions = cast(list[str], json_loads(raw.decode()))
            if newest_first:
                all_sessions.reverse()
            return all_sessions[offset : offset + limit]
        finally:
            client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        self.client.close()

    def _session_key(self) -> str:
        assert self.session_id, "Session ID must be set"
        return f"bsid-{self.session_id}"

    def _key(self, blueprint_id: str, key: str) -> str:
        assert self.session_id, "Session ID must be set"
        return f"{self._session_key()}:{blueprint_id}:{key}"

    def get(self, blueprint_id: str, key: str) -> Optional[Any]:
        full_key = self._key(blueprint_id, key)
        raw = self.client.get(full_key)
        if raw is None:
            return None
        return json_loads(raw.decode())

    def set(self, blueprint_id: str, key: str, value: Any) -> None:
        full_key = self._key(blueprint_id, key)
        self.client.set(full_key, json_dumps(value))

    def set_all(self, blueprint_id: str, data: dict[str, Any]) -> None:
        pipe = self.client.pipeline()
        for key, value in data.items():
            pipe.set(self._key(blueprint_id, key), json_dumps(value))
        pipe.execute()

    def get_all(self, blueprint_id: str) -> dict[str, Any]:
        assert self.session_id, "Session ID must be set"
        prefix_str = f"{self._session_key()}:{blueprint_id}:"

        data = {}
        cursor = 0
        while True:
            cursor, keys = self.client.scan(cursor, match=f"{prefix_str}*", count=1000)
            for key in keys:
                decoded_key = key.decode()
                clean_key = decoded_key[len(prefix_str) :]
                raw = self.client.get(key)
                if raw is not None:
                    data[clean_key] = json_loads(raw.decode())
            if cursor == 0:
                break
        return data

    def save_session(self, session: BlueprintSession) -> None:
        """Save a complete BlueprintSession object to storage.

        This stores the entire session including:
        - Session metadata (state, params, timestamps)
        - The main blueprint and all inner blueprints
        - Composite task mappings and contexts

        Parameters
        ----------
        session : BlueprintSession
            The session to save.
        """
        key = self._session_key()
        index_key = "session:index"

        # Check if this is a new session or update
        existing_raw = self.client.get(key)
        if existing_raw:
            existing_data = json_loads(existing_raw.decode())
            started_at = existing_data.get("started_at")
            ended_at = existing_data.get("ended_at")
        else:
            started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
            ended_at = None

        value = {
            "session": session,
            "started_at": started_at,
            "ended_at": ended_at,
        }

        index_value = _update_index(self.client, index_key, items_to_add=[self.session_id])

        pipe = self.client.pipeline()
        pipe.set(key, json_dumps(value))
        pipe.set(index_key, index_value)
        pipe.execute()

    def load_session(self) -> Optional[BlueprintSession]:
        """Load a complete BlueprintSession object from storage.

        Returns
        -------
        Optional[BlueprintSession]
            The loaded session, or None if not found.
        """
        data = self.load_session_with_metadata()
        if data:
            return data.get("session")
        return None

    def load_session_with_metadata(self) -> Optional[dict]:
        """Load a complete BlueprintSession object with metadata from storage.

        Returns
        -------
        Optional[dict]
            A dictionary containing 'session', 'started_at', and 'ended_at', or None if not found.
        """
        key = self._session_key()
        raw = self.client.get(key)
        if raw is None:
            return None
        return json_loads(raw.decode())

    def remove_session(self) -> None:
        """Remove a session and all its associated data from storage.

        Raises
        ------
        RequestedSessionNotFound
            If the session with the given ID is not found.
        """
        LOG.debug(f"Removing session {self.session_id} from Redis")

        session_key = self._session_key()
        if not self.client.exists(session_key):
            LOG.error(f"Session {self.session_id} not found in database")
            raise RequestedSessionNotFound(f"Session {self.session_id} not found")

        # Collect all keys associated with this session
        keys_to_delete = [session_key]
        cursor = 0
        while True:
            cursor, keys = self.client.scan(cursor, match=f"{session_key}:*", count=1000)
            keys_to_delete.extend(keys)
            if cursor == 0:
                break

        index_key = "session:index"
        index_value = _update_index(self.client, index_key, items_to_remove=[self.session_id])

        pipe = self.client.pipeline()
        pipe.set(index_key, index_value)
        pipe.delete(*keys_to_delete)
        pipe.execute()

        LOG.info(f"Session {self.session_id} deleted")


class BlueprintStorage(BaseBlueprintStorage):
    _DB = _BLUEPRINT_DB

    def __init__(self):
        self.client = _create_redis_client(self._DB)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        self.client.close()

    def add_blueprint(self, blueprint: Blueprint) -> None:
        """Store a blueprint with searchable metadata.

        Parameters
        ----------
        blueprint : Blueprint
            The blueprint to store.
        """
        LOG.debug(f"Storing blueprint {blueprint.id} in Redis")

        index_key = "blueprint:index"
        metadata_key = f"metadata:{blueprint.id}"
        blueprint_key = f"blueprint:{blueprint.id}"

        # Store metadata and serialized blueprint separately as blueprints may be large
        # and we might just want to query metadata
        metadata = {
            "id": blueprint.id,
            "name": blueprint.name,
            "version": blueprint.version,
            "description": blueprint.description,
            "task_count": len(blueprint.tasks),
            "uploaded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

        index_value = _update_index(self.client, index_key, items_to_add=[blueprint.id])

        pipe = self.client.pipeline()
        pipe.set(index_key, index_value)
        pipe.set(metadata_key, json_dumps(metadata))
        pipe.set(blueprint_key, json_dumps(blueprint))
        pipe.execute()

    def get_blueprint(self, blueprint_id: str) -> Blueprint:
        """Retrieve a blueprint by its ID.

        Parameters
        ----------
        blueprint_id : str
            The ID of the blueprint to retrieve.

        Returns
        -------
        Optional[Blueprint]
            The blueprint if found, None otherwise.
        """
        blueprint_key = f"blueprint:{blueprint_id}"
        try:
            raw = self.client.get(blueprint_key)
            if not raw:
                LOG.exception(f"Blueprint {blueprint_id} not found in database")
                raise RequestedBlueprintNotFound(f"Blueprint {blueprint_id} not found")

            return json_loads(raw.decode())  # type: ignore
        except Exception as ex:
            LOG.exception(f"Failed to retrieve blueprint {blueprint_id} - {ex}")
            raise

    def list_blueprints(self) -> list[dict[str, Any]]:
        """List all available blueprints in the database.

        Returns
        -------
        list[dict[str, Any]]
            A list of blueprint metadata dictionaries containing id, name,
            version, description, and task_count.
        """
        found_blueprints = []

        index_key = "blueprint:index"
        raw = self.client.get(index_key)
        if raw:
            index_data = cast(list[str], json_loads(raw.decode()))
        else:
            index_data = []

        for blueprint_id in index_data:
            result = self.client.get(f"metadata:{blueprint_id}")
            if result:
                found_blueprints.append(json_loads(result.decode()))

        return found_blueprints

    def remove_blueprint(self, blueprint_id: str) -> None:
        """Remove a blueprint from the database.

        Parameters
        ----------
        blueprint_id : str
            The ID of the blueprint to remove.

        Raises
        ------
        RequestedBlueprintNotFound
            If the blueprint with the given ID is not found.
        """
        LOG.debug(f"Removing blueprint {blueprint_id} from Redis")

        blueprint_key = f"blueprint:{blueprint_id}"
        if not self.client.exists(blueprint_key):
            LOG.error(f"Blueprint {blueprint_id} not found in database")
            raise RequestedBlueprintNotFound(f"Blueprint {blueprint_id} not found")

        index_key = "blueprint:index"
        index_value = _update_index(self.client, index_key, items_to_remove=[blueprint_id])

        metadata_key = f"metadata:{blueprint_id}"

        pipe = self.client.pipeline()
        pipe.set(index_key, index_value)
        pipe.delete(metadata_key, blueprint_key)
        pipe.execute()

        LOG.info(f"Blueprint {blueprint_id} deleted")


class ModelStorage(BaseModelStorage):
    _DB = _MODEL_DB

    def __init__(self):
        self.client = _create_redis_client(self._DB)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        self.client.close()

    def add_model(self, model_id: str, model: Any) -> None:
        """Store a model.

        Parameters
        ----------
        model_id : str
            The ID of the model.
        model : Any
            The model to store (must be COMPAS serializable).
        """
        LOG.debug(f"Storing model {model_id} in Redis")

        index_key = "model:index"
        key = f"model:{model_id}"
        index_value = _update_index(self.client, index_key, items_to_add=[model_id])

        pipe = self.client.pipeline()
        pipe.set(key, json_dumps(model))
        pipe.set(index_key, index_value)
        pipe.execute()

    def add_nesting(self, model_id: str, nesting: Any) -> None:
        """Store a nesting result for a model.

        Parameters
        ----------
        model_id : str
            The ID of the model.
        nesting : Any
            The nesting result to store (must be COMPAS serializable).

        Raises
        ------
        RequestedModelNotFound
            If the model with the given ID is not found.
        """
        LOG.debug(f"Storing nesting for model {model_id} in Redis")

        model_key = f"model:{model_id}"
        if not self.client.exists(model_key):
            LOG.error(f"Model {model_id} not found in database")
            raise RequestedModelNotFound(f"Model {model_id} not found")

        self.client.set(f"nesting:{model_id}", json_dumps(nesting))

    def get_nesting(self, model_id: str) -> Optional[Any]:
        """Retrieve a nesting result for a model.

        Parameters
        ----------
        model_id : str
            The ID of the model.

        Returns
        -------
        Optional[Any]
            The nesting result if found, None otherwise.
        """
        key = f"nesting:{model_id}"
        try:
            raw = self.client.get(key)
            if not raw:
                return None
            return json_loads(raw.decode())
        except Exception as ex:
            LOG.exception(f"Failed to retrieve nesting for model {model_id} - {ex}")
            raise

    def get_model(self, model_id: str) -> Any:
        """Retrieve a model by its ID.

        Parameters
        ----------
        model_id : str
            The ID of the model to retrieve.

        Returns
        -------
        Any
            The model if found.
        """
        key = f"model:{model_id}"
        try:
            raw = self.client.get(key)
            if not raw:
                LOG.error(f"Model {model_id} not found in database")
                raise RequestedModelNotFound(f"Model {model_id} not found")
            return json_loads(raw.decode())
        except Exception as ex:
            LOG.exception(f"Failed to retrieve model {model_id} - {ex}")
            raise

    def list_models(self) -> list[str]:
        """List all available model IDs in the database.

        Returns
        -------
        list[str]
            A list of model IDs.
        """
        index_key = "model:index"
        raw = self.client.get(index_key)
        if raw:
            return cast(list[str], json_loads(raw.decode()))
        return []

    def remove_model(self, model_id: str) -> None:
        """Remove a model from the database.

        Parameters
        ----------
        model_id : str
            The ID of the model to remove.

        Raises
        ------
        RequestedModelNotFound
            If the model with the given ID is not found.
        """
        LOG.debug(f"Removing model {model_id} from Redis")

        key = f"model:{model_id}"
        if not self.client.exists(key):
            LOG.error(f"Model {model_id} not found in database")
            raise RequestedModelNotFound(f"Model {model_id} not found")

        index_key = "model:index"
        index_value = _update_index(self.client, index_key, items_to_remove=[model_id])

        pipe = self.client.pipeline()
        pipe.set(index_key, index_value)
        pipe.delete(key)
        pipe.execute()

        LOG.info(f"Model {model_id} deleted")
