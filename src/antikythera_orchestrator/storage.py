import datetime
import logging
from typing import Any
from typing import Optional
from typing import cast

from compas.data import json_dumps
from compas.data import json_loads
from immudb import ImmudbClient
from immudb.datatypes import DeleteKeysRequest

from antikythera import config
from antikythera.models import Blueprint
from antikythera.models import BlueprintSession

LOG = logging.getLogger(__name__)


class RequestedBlueprintNotFound(Exception):
    """Raised when a requested blueprint is not found in storage."""

    pass


class RequestedModelNotFound(Exception):
    """Raised when a requested model is not found in storage."""

    pass


class RequestedSessionNotFound(Exception):
    """Raised when a requested session is not found in storage."""

    pass


def _create_immudb_client(db_name: str) -> ImmudbClient:
    client = ImmudbClient(max_grpc_message_length=config.IMMUDB_MAX_GRPC_MESSAGE_LENGTH)
    try:
        client.login(config.IMMUDB_USER, config.IMMUDB_PASSWORD)
    except KeyError:
        LOG.exception("Environment variable for immudb credentials ('IMMUDB_USER' and 'IMMUDB_PASSWORD') not set")
        raise
    except Exception as e:
        LOG.exception(f"Failed to connect to immudb: {e}")
        raise
    existing_dbs = client.databaseList()

    if db_name not in existing_dbs:
        client.createDatabase(db_name.encode())
    client.useDatabase(db_name.encode())

    return client


def _update_index(client: ImmudbClient, index_key: bytes, items_to_add: list[str] = None, items_to_remove: list[str] = None) -> bytes:
    items_to_add = items_to_add or []
    items_to_remove = items_to_remove or []

    match = client.get(index_key)
    if match:
        index_data = json_loads(match.value.decode())
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

    # we return the updated data instead of setting it here to allow batching multiple operations
    return json_dumps(index_data).encode()


def append_to_index(client: ImmudbClient, index_key: bytes, new_item: str) -> bytes:
    return _update_index(client, index_key, items_to_add=[new_item])


def remove_from_index(client: ImmudbClient, index_key: bytes, item_to_remove: str) -> bytes:
    return _update_index(client, index_key, items_to_remove=[item_to_remove])


class SessionStorage:
    SESSIONS_DB_NAME = "orchestrator_session"

    def __init__(self, session_id: str):
        self.client = _create_immudb_client(self.SESSIONS_DB_NAME)
        self.session_id = session_id

    @staticmethod
    def list_sessions(limit: int = 10, offset: int = 0, newest_first: bool = True) -> list[str]:
        client = _create_immudb_client(SessionStorage.SESSIONS_DB_NAME)

        try:
            index_key = b"session:index"
            match = client.get(index_key)
            if not match:
                return []

            index_data = json_loads(match.value.decode())
            all_sessions = cast(list[str], index_data)
            if newest_first:
                all_sessions.reverse()
            return all_sessions[offset : offset + limit]
        finally:
            client.shutdown()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        # self.client.logout()
        self.client.shutdown()

    def _session_key(self) -> str:
        assert self.session_id, "Session ID must be set"
        return f"bsid-{self.session_id}"

    def _key(self, blueprint_id: str, key: str) -> bytes:
        assert self.session_id, "Session ID must be set"
        return f"{self._session_key()}:{blueprint_id}:{key}".encode()

    def get(self, blueprint_id: str, key: str) -> Optional[Any]:
        full_key = self._key(blueprint_id, key)
        match = self.client.get(full_key)
        if match is None:
            return None

        bytes_value = match.value
        return json_loads(bytes_value.decode())

    def set(self, blueprint_id: str, key: str, value: Any) -> None:
        full_key = self._key(blueprint_id, key)
        json_value = json_dumps(value)
        self.client.set(full_key, json_value.encode())

    def set_all(self, blueprint_id: str, data: dict[str, Any]) -> None:
        all_data = {}
        for key, value in data.items():
            all_data[bytes(self._key(blueprint_id, key))] = json_dumps(value).encode()
        self.client.setAll(all_data)

    def get_all(self, blueprint_id: str) -> dict[str, Any]:
        assert self.session_id, "Session ID must be set"
        prefix_str = f"{self._session_key()}:{blueprint_id}:"
        prefix = prefix_str.encode()
        # TODO: Handle pagination if more than 1000 keys
        results = self.client.scan(b"", prefix, False, 1000)

        data = {}
        for key, value in results.items():
            decoded_key = key.decode()
            if decoded_key.startswith(prefix_str):
                clean_key = decoded_key[len(prefix_str) :]
                data[clean_key] = json_loads(value.decode())
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
        index_key = b"session:index"

        # Check if this is a new session or update
        existing = self.client.get(key.encode())
        if existing:
            existing_data = json_loads(existing.value.decode())
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

        # Maintain an index so that we can list all saved sessions
        index_value = append_to_index(self.client, index_key, self.session_id)

        self.client.setAll({key.encode(): json_dumps(value).encode(), index_key: index_value})

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
        match = self.client.get(key.encode())
        if match is None:
            return None

        return json_loads(match.value.decode())


class BlueprintStorage:
    BLUEPRINTS_DB_NAME = "orchestrator_blueprints"

    def __init__(self):
        self.client = _create_immudb_client(self.BLUEPRINTS_DB_NAME)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        # self.client.logout()
        self.client.shutdown()

    def add_blueprint(self, blueprint: Blueprint) -> None:
        """Store a blueprint with searchable metadata.

        Parameters
        ----------
        blueprint : Blueprint
            The blueprint to store.
        """
        LOG.debug(f"Storing blueprint {blueprint.id} in immudb")

        # and index storage is maintained separately from the bluprints and their metadata
        # this is done for lookup purposes as `scan` seems to have mysterious ways
        index_key = b"blueprint:index"
        metadata_key = f"metadata:{blueprint.id}".encode()
        blueprint_key = f"blueprint:{blueprint.id}".encode()

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

        metadata_value = json_dumps(metadata).encode()
        blueprint_value = json_dumps(blueprint).encode()
        blueprint_index_value = append_to_index(self.client, index_key, blueprint.id)

        # do it all in a single transaction
        self.client.setAll(
            {
                index_key: blueprint_index_value,
                metadata_key: metadata_value,
                blueprint_key: blueprint_value,
            }
        )

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
        blueprint_key = f"blueprint:{blueprint_id}".encode()
        try:
            match = self.client.get(blueprint_key)
            if not match:
                LOG.exception(f"Blueprint {blueprint_id} not found in database")
                raise RequestedBlueprintNotFound(f"Blueprint {blueprint_id} not found")

            return json_loads(match.value.decode())  # type: ignore
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

        index_key = b"blueprint:index"
        match = self.client.get(index_key)
        if match:
            index_data = json_loads(match.value.decode())
            index_data = cast(list[str], index_data)
        else:
            index_data = []

        for blueprint_id in index_data:
            result = self.client.get(f"metadata:{blueprint_id}".encode())
            if result:
                metadata = json_loads(result.value.decode())
                found_blueprints.append(metadata)

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
        LOG.debug(f"Removing blueprint {blueprint_id} from immudb")

        # First verify the blueprint exists
        blueprint_key = f"blueprint:{blueprint_id}".encode()
        match = self.client.get(blueprint_key)
        if not match:
            LOG.error(f"Blueprint {blueprint_id} not found in database")
            raise RequestedBlueprintNotFound(f"Blueprint {blueprint_id} not found")

        # Remove from index
        index_key = b"blueprint:index"
        blueprint_index_value = remove_from_index(self.client, index_key, blueprint_id)
        self.client.set(index_key, blueprint_index_value)

        # Delete the blueprint and metadata keys
        metadata_key = f"metadata:{blueprint_id}".encode()
        delete_request = DeleteKeysRequest(keys=[metadata_key, blueprint_key])
        self.client.delete(delete_request)

        LOG.info(f"Blueprint {blueprint_id} deleted")


class ModelStorage:
    MODELS_DB_NAME = "orchestrator_models"

    def __init__(self):
        self.client = _create_immudb_client(self.MODELS_DB_NAME)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        # self.client.logout()
        self.client.shutdown()

    def add_model(self, model_id: str, model: Any) -> None:
        """Store a model.

        Parameters
        ----------
        model_id : str
            The ID of the model.
        model : Any
            The model to store (must be COMPAS serializable).
        """
        LOG.debug(f"Storing model {model_id} in immudb")

        # Update index
        index_key = b"model:index"

        key = f"model:{model_id}".encode()
        value = json_dumps(model).encode()
        index_value = append_to_index(self.client, index_key, model_id)

        self.client.setAll({key: value, index_key: index_value})

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
        LOG.debug(f"Storing nesting for model {model_id} in immudb")

        # Verify model exists
        model_key = f"model:{model_id}".encode()
        match = self.client.get(model_key)
        if not match:
            LOG.error(f"Model {model_id} not found in database")
            raise RequestedModelNotFound(f"Model {model_id} not found")

        key = f"nesting:{model_id}".encode()
        value = json_dumps(nesting).encode()
        self.client.set(key, value)

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
        key = f"nesting:{model_id}".encode()
        try:
            match = self.client.get(key)
            if not match:
                return None

            return json_loads(match.value.decode())
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
        key = f"model:{model_id}".encode()
        try:
            match = self.client.get(key)
            if not match:
                LOG.error(f"Model {model_id} not found in database")
                raise RequestedModelNotFound(f"Model {model_id} not found")

            return json_loads(match.value.decode())
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
        index_key = b"model:index"
        match = self.client.get(index_key)
        if match:
            index_data = json_loads(match.value.decode())
            return cast(list[str], index_data)
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
        LOG.debug(f"Removing model {model_id} from immudb")

        # First verify the model exists
        key = f"model:{model_id}".encode()
        match = self.client.get(key)
        if not match:
            LOG.error(f"Model {model_id} not found in database")
            raise RequestedModelNotFound(f"Model {model_id} not found")

        # Remove from index
        index_key = b"model:index"
        index_value = remove_from_index(self.client, index_key, model_id)
        self.client.set(index_key, index_value)

        # Delete the model key
        delete_request = DeleteKeysRequest(keys=[key])
        self.client.delete(delete_request)

        LOG.info(f"Model {model_id} deleted")
