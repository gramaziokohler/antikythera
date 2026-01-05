from dataclasses import dataclass
from typing import Dict
from typing import List
from typing import Optional


@dataclass
class MockGetResponse:
    value: bytes


class MockImmudbClient:
    """A mock implementation of ImmudbClient for testing and in-memory usage."""

    # Class-level storage to persist data across multiple client instances
    # mimicking a persistent database server
    _databases: Dict[str, Dict[bytes, bytes]] = {}

    def __init__(self):
        self.current_db: Optional[str] = None
        self.logged_in = False

    def login(self, username, password):
        self.logged_in = True

    def databaseList(self) -> List[str]:
        return list(self._databases.keys())

    def createDatabase(self, db_name: bytes):
        name = db_name.decode()
        if name not in self._databases:
            self._databases[name] = {}

    def useDatabase(self, db_name: bytes):
        name = db_name.decode()
        if name not in self._databases:
            # In the real client, this might fail if DB doesn't exist,
            # but storage.py creates it if it's missing from the list.
            self._databases[name] = {}
        self.current_db = name

    def shutdown(self):
        pass

    def get(self, key: bytes) -> Optional[MockGetResponse]:
        if not self.current_db:
            raise Exception("No database selected")

        val = self._databases[self.current_db].get(key)
        if val is not None:
            return MockGetResponse(val)
        return None

    def set(self, key: bytes, value: bytes):
        if not self.current_db:
            raise Exception("No database selected")
        self._databases[self.current_db][key] = value

    def setAll(self, kv_pairs: Dict[bytes, bytes]):
        if not self.current_db:
            raise Exception("No database selected")
        self._databases[self.current_db].update(kv_pairs)

    def scan(self, seekKey: bytes, prefix: bytes, desc: bool, limit: int) -> Dict[bytes, bytes]:
        if not self.current_db:
            raise Exception("No database selected")

        db = self._databases[self.current_db]
        result = {}

        # Simplified scan implementation
        # storage.py uses: results = self.client.scan(b"", prefix, False, 1000)
        for k, v in db.items():
            if k.startswith(prefix):
                result[k] = v

        return result

    def delete(self, request):
        # request is expected to be immudb.datatypes.DeleteKeysRequest
        if not self.current_db:
            raise Exception("No database selected")

        for key in request.keys:
            if key in self._databases[self.current_db]:
                del self._databases[self.current_db][key]

    @classmethod
    def clear_all(cls):
        """Helper to clear all data (useful for test teardown)."""
        cls._databases = {}
