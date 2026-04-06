from unittest.mock import patch

import fakeredis
import pytest
from compas_eve.codecs import ProtobufMessageCodec
from compas_eve.memory import InMemoryTransport


@pytest.fixture(scope="module")
def in_memory_transport():
    return InMemoryTransport(codec=ProtobufMessageCodec())


@pytest.fixture
def mock_storage():
    """Patch the Redis storage backend with an in-memory fakeredis server.

    Each test gets a fresh FakeServer so state never leaks between tests.
    All storage classes (session/blueprint/model) share the same server and
    use separate logical databases (db=0/1/2), exactly mirroring real Redis.
    """
    server = fakeredis.FakeServer()

    def fake_create_redis_client(db: int):
        return fakeredis.FakeRedis(server=server, db=db, decode_responses=False)

    with patch("antikythera_orchestrator.storage.redis_storage._create_redis_client", side_effect=fake_create_redis_client):
        yield


# Backward-compatible alias so existing test signatures don't need changing.
mock_immudb = mock_storage


@pytest.fixture
def mock_transport_orchestrator(in_memory_transport):
    with patch("antikythera_orchestrator.orchestrator._get_eve_transport", return_value=in_memory_transport) as mock:
        yield mock


@pytest.fixture
def mock_transport_launcher(in_memory_transport):
    with patch("antikythera_agents.launcher._get_eve_transport", return_value=in_memory_transport) as mock:
        yield mock


@pytest.fixture(autouse=True)
def mock_agent_discovery():
    """Prevent plugin discovery from loading external agents (e.g., fall_demo_2025 agents that require ROS)."""
    with patch("antikythera_agents.launcher._ensure_agents"):
        yield


@pytest.fixture
def cleanup_manager():
    """Fixture to manage cleanup of orchestrators and launchers."""
    resources = []

    class Manager:
        def register(self, resource):
            resources.append(resource)
            return resource

    yield Manager()

    for resource in reversed(resources):
        if hasattr(resource, "stop"):
            resource.stop()


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
