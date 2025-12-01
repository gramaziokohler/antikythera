import logging
import os
from typing import Any
from typing import Optional

from compas.data import json_dumps
from compas.data import json_loads
from immudb import ImmudbClient

LOG = logging.getLogger(__name__)


class SessionStorage:
    SESSION_DB_NAME = "orchestrator_session"

    def __init__(self):
        self.client = ImmudbClient()
        try:
            self.client.login(os.environ["IMMUDB_USER"], os.environ["IMMUDB_PASSWORD"])
        except KeyError:
            LOG.exception("Environment variable for immudb credentials ('IMMUDB_USER' and 'IMMUDB_PASSWORD') not set")
            raise
        except Exception as e:
            LOG.exception(f"Failed to connect to immudb: {e}")
            raise
        self._ensure_database()

    def _ensure_database(self) -> None:
        existing_dbs = self.client.databaseList()
        if self.SESSION_DB_NAME not in existing_dbs:
            self.client.createDatabase(self.SESSION_DB_NAME.encode())
        self.client.useDatabase(self.SESSION_DB_NAME.encode())
        #  TODO: should we wipe the existing database if it already exists? the data persists..

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
