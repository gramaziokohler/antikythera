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

LOG = logging.getLogger(__name__)


class RequestedBlueprintNotFound(Exception):
    """Raised when a requested blueprint is not found in storage."""

    pass


def _create_immudb_client(db_name: str) -> ImmudbClient:
    client = ImmudbClient()
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

    LOG.debug(f"Connected to immudb database '{db_name}' as user '{config.IMMUDB_USER}'")
    return client


class SessionStorage:
    SESSIONS_DB_NAME = "orchestrator_session"

    def __init__(self):
        self.client = _create_immudb_client(self.SESSIONS_DB_NAME)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        # self.client.logout()
        self.client.shutdown()

    def _key(self, blueprint_id: str, key: str) -> bytes:
        return f"{blueprint_id}:{key}".encode()

    def get(self, blueprint_id: str, key: str) -> Optional[Any]:
        full_key = self._key(blueprint_id, key)
        try:
            match = self.client.get(full_key)
            bytes_value = match.value
            return json_loads(bytes_value.decode())
        except KeyError:
            return None

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
        prefix = f"{blueprint_id}:".encode()
        # TODO: Handle pagination if more than 1000 keys
        results = self.client.scan(b"", prefix, False, 1000)

        data = {}
        for key, value in results.items():
            decoded_key = key.decode()
            if decoded_key.startswith(f"{blueprint_id}:"):
                clean_key = decoded_key[len(blueprint_id) + 1 :]
                data[clean_key] = json_loads(value.decode())
        return data


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

        match = self.client.get(index_key)
        if match:
            index_data = json_loads(match.value.decode())
            index_data = cast(list[str], index_data)
        else:
            index_data = []

        if blueprint.id not in index_data:
            index_data.append(blueprint.id)

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
        blueprint_index_value = json_dumps(index_data).encode()

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
        match = self.client.get(index_key)
        if match:
            index_data = json_loads(match.value.decode())
            index_data = cast(list[str], index_data)

            if blueprint_id in index_data:
                index_data.remove(blueprint_id)
                # Update the index
                blueprint_index_value = json_dumps(index_data).encode()
                self.client.set(index_key, blueprint_index_value)
        else:
            LOG.warning("Blueprint index not found, skipping index update")

        # Delete the blueprint and metadata keys
        metadata_key = f"metadata:{blueprint_id}".encode()
        delete_request = DeleteKeysRequest(keys=[metadata_key, blueprint_key])
        self.client.delete(delete_request)

        LOG.info(f"Blueprint {blueprint_id} deleted")
