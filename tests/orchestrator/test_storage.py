import json

import pytest

from antikythera_orchestrator.storage import append_to_index
from antikythera_orchestrator.storage import remove_from_index
from antikythera_orchestrator.storage_mock import MockImmudbClient


@pytest.fixture
def mock_client():
    MockImmudbClient.clear_all()
    client = MockImmudbClient()
    client.createDatabase(b"test_db")
    client.useDatabase(b"test_db")
    return client


def test_append_to_index_empty(mock_client):
    index_key = b"test:index"
    item = "item1"

    # Execute
    result_bytes = append_to_index(mock_client, index_key, item)

    # Verify result
    result_data = json.loads(result_bytes.decode())
    assert item in result_data
    assert len(result_data) == 1

    # Verify DB state is unchanged (function is pure regarding writes)
    assert mock_client.get(index_key) is None


def test_append_to_index_existing(mock_client):
    index_key = b"test:index"
    initial_items = ["item1", "item2"]
    mock_client.set(index_key, json.dumps(initial_items).encode())

    new_item = "item3"
    result_bytes = append_to_index(mock_client, index_key, new_item)

    result_data = json.loads(result_bytes.decode())
    assert new_item in result_data
    assert len(result_data) == 3
    assert set(result_data) == {"item1", "item2", "item3"}


def test_append_to_index_duplicate(mock_client):
    index_key = b"test:index"
    initial_items = ["item1"]
    mock_client.set(index_key, json.dumps(initial_items).encode())

    result_bytes = append_to_index(mock_client, index_key, "item1")

    result_data = json.loads(result_bytes.decode())
    assert result_data == ["item1"]
    assert len(result_data) == 1


def test_remove_from_index_existing(mock_client):
    index_key = b"test:index"
    initial_items = ["item1", "item2"]
    mock_client.set(index_key, json.dumps(initial_items).encode())

    result_bytes = remove_from_index(mock_client, index_key, "item1")

    result_data = json.loads(result_bytes.decode())
    assert "item1" not in result_data
    assert "item2" in result_data
    assert len(result_data) == 1


def test_remove_from_index_non_existing(mock_client):
    index_key = b"test:index"
    initial_items = ["item1"]
    mock_client.set(index_key, json.dumps(initial_items).encode())

    # Try removing item that isn't there
    result_bytes = remove_from_index(mock_client, index_key, "item2")

    result_data = json.loads(result_bytes.decode())
    assert result_data == ["item1"]


def test_remove_from_index_empty_db(mock_client):
    index_key = b"test:index"
    # Index doesn't exist yet

    result_bytes = remove_from_index(mock_client, index_key, "item1")

    result_data = json.loads(result_bytes.decode())
    assert result_data == []
