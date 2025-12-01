from typing import Optional
from typing import Any

from immudb import ImmudbClient

from compas.data import json_loads
from compas.data import json_dumps

from antikythera import config


class SessionStorage:
    def __init__(self):
        self.client = ImmudbClient()
        self.client.login(config.IMMUDB_USER, config.IMMUDB_PASSWORD)
        self.client.useDatabase(config.IMMUDB_DATABASE.encode())

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.client.logout()
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

    def set(self, blueprint_id: str, key: str, value : Any) -> None:
        full_key = self._key(blueprint_id, key)
        json_value = json_dumps(value)
        self.client.set(full_key, json_value.encode())
    
    def set_all(self, blueprint_id: str, data: dict[str, Any]) -> None:
        all_data = {}
        for key, value in data.items():
            all_data[bytes(self._key(blueprint_id, key))] = json_dumps(value).encode()
        self.client.setAll(all_data)
