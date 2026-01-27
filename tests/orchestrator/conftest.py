from unittest.mock import patch

import pytest
from compas_eve.codecs import ProtobufMessageCodec
from compas_eve.memory import InMemoryTransport

from antikythera_orchestrator.storage_mock import MockImmudbClient


@pytest.fixture(scope="module")
def in_memory_transport():
    return InMemoryTransport(codec=ProtobufMessageCodec())


@pytest.fixture
def mock_immudb():
    # Reset the mock storage before each test
    MockImmudbClient._databases = {}
    
    def side_effect(db_name):
        client = MockImmudbClient()
        client.login("user", "password")
        if db_name not in client.databaseList():
            client.createDatabase(db_name.encode())
        client.useDatabase(db_name.encode())
        return client

    with patch("antikythera_orchestrator.storage._create_immudb_client", side_effect=side_effect) as mock:
        yield mock


@pytest.fixture
def mock_transport_orchestrator(in_memory_transport):
    with patch("antikythera_orchestrator.orchestrator._get_eve_transport", return_value=in_memory_transport) as mock:
        yield mock


@pytest.fixture
def mock_transport_launcher(in_memory_transport):
    with patch("antikythera_agents.launcher._get_eve_transport", return_value=in_memory_transport) as mock:
        yield mock


@pytest.fixture(autouse=True)
def fast_system_agents():
    """Patch system agents to run instantly for tests."""
    with (
        patch("antikythera_orchestrator.system_agents.SystemAgent.start_process") as mock_start,
        patch("antikythera_orchestrator.system_agents.SystemAgent.end_process") as mock_end,
    ):
        # Configure mocks to return expected dictionary and be fast
        mock_start.return_value = {"process_start_time": 0.0}
        mock_end.return_value = {"process_end_time": 0.0}

        # Important: set __name__ because Agent.list_tools accesses it
        mock_start.__name__ = "start_process"
        mock_end.__name__ = "end_process"

        # Restore decorator attributes so they are recognized as tools
        mock_start._tool_name = "start"
        mock_end._tool_name = "end"

        yield (mock_start, mock_end)
