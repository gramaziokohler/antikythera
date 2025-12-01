import datetime
import logging
import os
from typing import Any
from typing import Optional
from typing import cast

from compas.data import json_dumps
from compas.data import json_loads
from immudb import ImmudbClient

from antikythera.models import Blueprint

LOG = logging.getLogger(__name__)


def _create_immudb_client(db_name: str) -> ImmudbClient:
    client = ImmudbClient()
    try:
        client.login(os.environ["IMMUDB_USER"], os.environ["IMMUDB_PASSWORD"])
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


class SessionStorage:
    SESSIONS_DB_NAME = "orchestrator_session"

    def __init__(self):
        self.client = _create_immudb_client(self.SESSIONS_DB_NAME)

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


class BlueprintStorage:
    BLUEPRINTS_DB_NAME = "orchestrator_blueprints"

    def __init__(self):
        self.client = _create_immudb_client(self.BLUEPRINTS_DB_NAME)

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

    def get_blueprint(self, blueprint_id: str) -> Optional[Blueprint]:
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
            bytes_value = match.value
            return json_loads(bytes_value.decode())  # type: ignore
        except KeyError:
            LOG.debug(f"Blueprint {blueprint_id} not found in database")
            return None
        except Exception:
            LOG.exception(f"Failed to retrieve blueprint {blueprint_id}")
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
