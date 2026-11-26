import logging
import os
import socket
import sys

import pytest


@pytest.fixture(autouse=True)
def setup_logging():
    logging.basicConfig(level=logging.DEBUG, format="[%(name)s] %(message)s", stream=sys.stdout, force=True)


NATS_TEST_URL = os.getenv("NATS_TEST_URL", "nats://127.0.0.1:4222")
# Set in CI, where a server is started for the tests: a missing server is then a failure, not a skip.
NATS_TEST_REQUIRED = os.getenv("NATS_TEST_REQUIRED", "").lower() in ("1", "true", "yes")


def _nats_reachable(url: str) -> bool:
    host_port = url.split("://", 1)[-1].rsplit("@", 1)[-1]
    host, _, port = host_port.partition(":")
    try:
        with socket.create_connection((host, int(port or 4222)), timeout=0.5):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def nats_url():
    """URL of a NATS server with JetStream for the NATS tests (env NATS_TEST_URL).

    Skips them if none is reachable, unless NATS_TEST_REQUIRED is set.
    """
    if NATS_TEST_REQUIRED:
        import nats  # noqa: F401
    else:
        pytest.importorskip("nats")
    if not _nats_reachable(NATS_TEST_URL):
        if NATS_TEST_REQUIRED:
            pytest.fail(f"NATS_TEST_REQUIRED is set but no NATS server is reachable at {NATS_TEST_URL}")
        pytest.skip(f"no NATS server at {NATS_TEST_URL} (start one with: docker run -p 4222:4222 nats -js)")
    return NATS_TEST_URL


@pytest.fixture
def nats_storage(nats_url):
    """A NatsStorage on its own bucket prefix, deleted afterwards."""
    import asyncio
    import uuid

    import nats

    from antikythera_orchestrator.storage.nats_storage import NatsStorage

    prefix = f"test-{uuid.uuid4().hex[:8]}"
    storage = NatsStorage(nats_url, prefix=prefix)
    yield storage
    storage.close()

    async def cleanup():
        client = await nats.connect(nats_url)
        js = client.jetstream()
        for kind in ("sessions", "session-data", "blueprints", "models"):
            try:
                await js.delete_object_store(f"{prefix}-{kind}")
            except Exception:
                pass
        await client.close()

    asyncio.run(cleanup())
